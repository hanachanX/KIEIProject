#ifndef USE_CA_CD
#define USE_CA_CD 0      // 1: 詰み・不詰の記憶(ca, cd)も残す（従来どおり）　0: やめる（既定。メモリが約15%減る）
#endif
#ifndef ALLCAP
#define ALLCAP 1
#endif
#include "tsume.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#if defined(_MSC_VER)
#include <intrin.h>
#endif

#ifndef ORD
#define ORD 1
#endif
#ifndef AORD
#define AORD 0
#endif
#ifndef TSUME_CAP
#define TSUME_CAP 40000000
#endif
namespace {
constexpr int P=1,L=2,N=3,S=4,G=5,B=6,R=7,K=8;
const int totals[9]={0,18,4,4,4,4,2,2,0};
const int promoted[15]={0,9,10,11,12,0,13,14,0,0,0,0,0,0,0};
const char symbols[]=" PLNSGBRK";
int base(int p) { return p>=13?p-7:p>=9?p-8:p; }
int color_of(int p) { return p<0?1:0; }
int sign(int c) { return c?-1:1; }
bool zone(int sq,int c) { return c?sq/9>=6:sq/9<=2; }
bool mobile(int p,int sq,int c) {
    int r=c?8-sq/9:sq/9;
    return !((p==P||p==L)&&r==0) && !(p==N&&r<=1);
}
struct Move {
    int from=-1,to=0,drop=0; bool promotion=false;
    std::string usi() const {
        auto square=[](int s) { std::string v; v+=char('9'-s%9);v+=char('a'+s/9);return v; };
        return (from<0?std::string(1,symbols[drop])+"*":square(from))+
            square(to)+(promotion?"+":"");
    }
};
Move parse_move(const std::string& text) {
    auto square=[](char f,char r) {
        if(f<'1'||f>'9'||r<'a'||r>'i')throw std::invalid_argument("Invalid USI square");
        return (r-'a')*9+'9'-f;
    };
    if(text.size()==4&&text[1]=='*') {
        const char* p=std::strchr(symbols,text[0]);
        if(!p||p==symbols||p-symbols>=K)throw std::invalid_argument("Invalid drop");
        return {-1,square(text[2],text[3]),int(p-symbols),false};
    }
    if((text.size()!=4&&text.size()!=5)||(text.size()==5&&text[4]!='+'))throw std::invalid_argument("Invalid USI move");
    return {square(text[0],text[1]),square(text[2],text[3]),0,text.size()==5};
}
struct SmallOrder {
    int v[8];int n=0;
    void push_back(int x){v[n++]=x;}
    void clear(){n=0;}
    void erase_value(int x){int j=0;for(int i=0;i<n;++i)if(v[i]!=x)v[j++]=v[i];n=j;}
    const int* begin() const {return v;}
    const int* end() const {return v+n;}
};

// Set to 0 when comparing with the previous full-board hashing implementation.
#ifndef TSUME_USE_ZOBRIST
#define TSUME_USE_ZOBRIST 1
#endif

#ifndef TSUME_VERIFY_ZOBRIST
#define TSUME_VERIFY_ZOBRIST 0
#endif

struct ZobristKey {
    uint64_t low = 0;
    uint64_t high = 0;

    bool operator==(const ZobristKey& other) const {
        return low == other.low && high == other.high;
    }
    void xor_with(const ZobristKey& other) {
        low ^= other.low;
        high ^= other.high;
    }
};

// Fixed seeds make the keys reproducible across runs and builds.
struct ZobristTables {
    std::array<std::array<ZobristKey, 29>, 81> squares{};
    std::array<std::array<std::array<ZobristKey, 19>, 7>, 2> hands{};
    ZobristKey white_turn;

    static uint64_t mix(uint64_t value) {
        value += 0x9E3779B97F4A7C15ULL;
        value = (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9ULL;
        value = (value ^ (value >> 27)) * 0x94D049BB133111EBULL;
        return value ^ (value >> 31);
    }

    static ZobristKey token(uint64_t identity) {
        return {mix(identity ^ 0x243F6A8885A308D3ULL),
                mix(identity ^ 0x13198A2E03707344ULL)};
    }

    static ZobristKey hand_token(int color, int piece, int count) {
        if (count == 0) return {};
        // Preserve the existing representation even for nonstandard hand counts.
        const uint64_t identity = 0x2000000000000000ULL
            | (uint64_t(color) << 40) | (uint64_t(piece) << 32)
            | uint64_t(uint32_t(count));
        return token(identity);
    }

    ZobristTables() {
        for (int square = 0; square < 81; ++square) {
            for (int piece = -14; piece <= 14; ++piece) {
                if (piece == 0) continue;
                squares[square][piece + 14] = token(
                    0x1000000000000000ULL | (uint64_t(square) << 8)
                    | uint64_t(piece + 14));
            }
        }
        for (int color = 0; color < 2; ++color)
            for (int piece = P; piece < K; ++piece)
                for (int count = 0; count <= 18; ++count)
                    hands[color][piece - 1][count] = hand_token(color, piece, count);
        white_turn = token(0x3000000000000000ULL);
    }

    static const ZobristTables& get() {
        static const ZobristTables tables;
        return tables;
    }

    ZobristKey hand_key(int color, int piece, int count) const {
        if (count >= 0 && count <= 18)
            return hands[color][piece - 1][count];
        return hand_token(color, piece, count);
    }
};


#ifndef TSUME_VERIFY_BITBOARDS
#define TSUME_VERIFY_BITBOARDS 0
#endif

// Squares 0..63 occupy low; squares 64..80 occupy the low 17 bits of high.
struct Bitboard81 {
    uint64_t low = 0;
    uint64_t high = 0;

    bool operator==(const Bitboard81& other) const {
        return low == other.low && high == other.high;
    }

    bool contains(int square) const {
        const uint64_t word = square < 64 ? low : high;
        return (word & (1ULL << (square % 64))) != 0;
    }

    void intersect(const Bitboard81& other) {
        low &= other.low;
        high &= other.high;
    }

    void exclude(const Bitboard81& other) {
        low &= ~other.low;
        high &= ~other.high;
    }

    // Call the bit-scan intrinsic only on a nonzero word.
    int pop_first() {
        uint64_t* word = &low;
        int offset = 0;
        if (low == 0) {
            if (high == 0) return -1;
            word = &high;
            offset = 64;
        }
#if defined(_MSC_VER)
        unsigned long index;
        _BitScanForward64(&index, *word);
#else
        const unsigned index = unsigned(__builtin_ctzll(*word));
#endif
        *word &= *word - 1;
        return offset + int(index);
    }

    int pop_last() {
        uint64_t* word = &high;
        int offset = 64;
        if (high == 0) {
            if (low == 0) return -1;
            word = &low;
            offset = 0;
        }
#if defined(_MSC_VER)
        unsigned long index;
        _BitScanReverse64(&index, *word);
#else
        const unsigned index = 63u - unsigned(__builtin_clzll(*word));
#endif
        *word &= ~(1ULL << index);
        return offset + int(index);
    }

    void set(int square, bool present) {
        uint64_t& word = square < 64 ? low : high;
        const uint64_t mask = 1ULL << (square % 64);
        if (present) word |= mask;
        else word &= ~mask;
    }
};


#ifndef TSUME_USE_BETWEEN_TABLES
#define TSUME_USE_BETWEEN_TABLES 1
#endif

// Strictly between two aligned squares. Endpoints are always excluded.
static Bitboard81 between_squares_legacy(int from, int to) {
    Bitboard81 result;
    if (from < 0 || from >= 81 || to < 0 || to >= 81 || from == to) return result;
    const int dr = to / 9 - from / 9, df = to % 9 - from % 9;
    if (dr != 0 && df != 0 && std::abs(dr) != std::abs(df)) return result;
    const int step = ((dr > 0) - (dr < 0)) * 9 + ((df > 0) - (df < 0));
    for (int square = from + step; square != to; square += step) result.set(square, true);
    return result;
}

struct BetweenSquareTables {
    std::array<std::array<Bitboard81, 81>, 81> masks{};
    BetweenSquareTables() {
        for (int from = 0; from < 81; ++from)
            for (int to = 0; to < 81; ++to)
                masks[from][to] = between_squares_legacy(from, to);
    }
    static const BetweenSquareTables& get() {
        static const BetweenSquareTables tables;
        return tables;
    }
};

static Bitboard81 between_squares(int from, int to) {
#if TSUME_USE_BETWEEN_TABLES
    if (from < 0 || from >= 81 || to < 0 || to >= 81) return {};
    return BetweenSquareTables::get().masks[from][to];
#else
    return between_squares_legacy(from, to);
#endif
}

// Preserve historical ordering: king -> checker, not unconditional square order.
static void append_between_squares(Bitboard81 mask, int king, int checker, std::vector<int>& out) {
    if (checker > king) {
        for (int square = mask.pop_first(); square >= 0; square = mask.pop_first()) out.push_back(square);
    } else {
        for (int square = mask.pop_last(); square >= 0; square = mask.pop_last()) out.push_back(square);
    }
}

#ifndef TSUME_USE_STEP_ATTACKS
#define TSUME_USE_STEP_ATTACKS 1
#endif
#ifndef TSUME_VERIFY_ATTACKS
#define TSUME_VERIFY_ATTACKS 0
#endif

// Fixed attacks ignore occupancy. Promoted pawn/lance/knight/silver share gold.
struct StepAttackTables {
    enum Slot { Pawn, Knight, Silver, Gold, King, Count };
    std::array<std::array<std::array<Bitboard81, 81>, Count>, 2> masks{};

    static int slot(int piece) {
        switch (piece) {
        case P: return Pawn;
        case N: return Knight;
        case S: return Silver;
        case G: case 9: case 10: case 11: case 12: return Gold;
        case K: return King;
        default: return -1;
        }
    }

    StepAttackTables() {
        for (int color = 0; color < 2; ++color) {
            for (int square = 0; square < 81; ++square) {
                const int row = square / 9;
                const int file = square % 9;
                const int forward = color == 0 ? -1 : 1;
                auto add = [&](int kind, int row_delta, int file_delta) {
                    const int target_row = row + forward * row_delta;
                    const int target_file = file + file_delta;
                    if (target_row >= 0 && target_row < 9
                        && target_file >= 0 && target_file < 9)
                        masks[color][kind][square].set(target_row * 9 + target_file, true);
                };
                add(Pawn, 1, 0);
                add(Knight, 2, -1);
                add(Knight, 2, 1);
                for (int file_delta : {-1, 0, 1}) {
                    add(Silver, 1, file_delta);
                    add(Gold, 1, file_delta);
                }
                add(Silver, -1, -1);
                add(Silver, -1, 1);
                add(Gold, 0, -1);
                add(Gold, 0, 1);
                add(Gold, -1, 0);
                for (int row_delta : {-1, 0, 1})
                    for (int file_delta : {-1, 0, 1})
                        if (row_delta != 0 || file_delta != 0)
                            add(King, row_delta, file_delta);
            }
        }
    }

    static const StepAttackTables& get() {
        static const StepAttackTables tables;
        return tables;
    }
};

#ifndef TSUME_USE_SLIDER_MAGIC
#define TSUME_USE_SLIDER_MAGIC 1
#endif
#include "slider_magic.h"

#ifndef TSUME_USE_BITBOARD_MOVES
#define TSUME_USE_BITBOARD_MOVES 1
#endif
#ifndef TSUME_USE_BITBOARD_FUTILE_CAPTURES
#define TSUME_USE_BITBOARD_FUTILE_CAPTURES 1
#endif
#ifndef TSUME_USE_BITBOARD_PAWN_DROP
#define TSUME_USE_BITBOARD_PAWN_DROP 1
#endif
#ifndef TSUME_USE_BITBOARD_CHECKERS
#define TSUME_USE_BITBOARD_CHECKERS 1
#endif
#ifndef TSUME_USE_BITBOARD_CHECKS
#define TSUME_USE_BITBOARD_CHECKS 1
#endif
#ifndef TSUME_USE_DIRECT_RAY_CHECKS
#define TSUME_USE_DIRECT_RAY_CHECKS 1
#endif
#ifndef TSUME_USE_BITBOARD_ATTACKED
#define TSUME_USE_BITBOARD_ATTACKED 1
#endif
#ifndef TSUME_USE_BITBOARD_EVASIONS
#define TSUME_USE_BITBOARD_EVASIONS 1
#endif
#ifndef TSUME_VERIFY_MOVES
#define TSUME_VERIFY_MOVES 0
#endif

#ifndef TSUME_USE_CACHED_KINGS
#define TSUME_USE_CACHED_KINGS 1
#endif
#ifndef TSUME_VERIFY_KING_CACHE
#define TSUME_VERIFY_KING_CACHE TSUME_VERIFY_BITBOARDS
#endif

#ifndef TSUME_USE_CACHED_PAWN_FILES
#define TSUME_USE_CACHED_PAWN_FILES 1
#endif
#ifndef TSUME_VERIFY_PAWN_FILES
#define TSUME_VERIFY_PAWN_FILES TSUME_VERIFY_BITBOARDS
#endif

#ifndef TSUME_USE_BITBOARD_SUPPORT
#define TSUME_USE_BITBOARD_SUPPORT 1
#endif

#ifndef TSUME_USE_BITBOARD_INVERSE
#define TSUME_USE_BITBOARD_INVERSE 1
#endif

struct Board {
    std::array<int,81> sq{};
    std::array<std::array<int,9>,2> hand{};
    std::array<SmallOrder,2> order;
    // 29 bits in the previous 32-bit turn slot. 81 means no king.
    // Counts also cover synthetic duplicate-king positions used by verification.
    unsigned turn : 1;
    unsigned king_black : 7;
    unsigned king_white : 7;
    unsigned kings_black : 7;
    unsigned kings_white : 7;

    Board() : turn(0), king_black(81), king_white(81), kings_black(0), kings_white(0) {}

    int cached_king(int color) const {
        const int square = color ? king_white : king_black;
        return square == 81 ? -1 : square;
    }
    int king_count(int color) const { return color ? kings_white : kings_black; }
    void store_king_state(int color, int square, int count) {
        if (color) { king_white = square; kings_white = count; }
        else { king_black = square; kings_black = count; }
    }
    void update_king_cache(int square, int old_piece, int new_piece) {
        if (old_piece == new_piece) return;
        if (old_piece == K || old_piece == -K) {
            const int color = color_of(old_piece), count = king_count(color) - 1;
            int position = cached_king(color);
            if (count == 0) position = -1;
            else if (position == square) {
                // Only duplicate-king removal needs a scan. The square array
                // already contains the replacement piece at this point.
                position = -1;
                for (int from = 0; from < 81; ++from)
                    if (sq[from] == sign(color) * K) { position = from; break; }
            }
            store_king_state(color, position < 0 ? 81 : position, count);
        }
        if (new_piece == K || new_piece == -K) {
            const int color = color_of(new_piece), count = king_count(color) + 1;
            const int previous = cached_king(color);
            const int position = previous < 0 || square < previous ? square : previous;
            store_king_state(color, position, count);
        }
    }
    void verify_king_cache() const {
#if TSUME_VERIFY_KING_CACHE
        int positions[2] = {-1,-1}, counts[2] = {0,0};
        for (int square = 0; square < 81; ++square)
            if (sq[square] == K || sq[square] == -K) {
                const int color = color_of(sq[square]);
                if (positions[color] < 0) positions[color] = square;
                ++counts[color];
            }
        for (int color = 0; color < 2; ++color)
            if (cached_king(color) != positions[color] || king_count(color) != counts[color]) {
                std::fprintf(stderr, "Incremental/reference king location or count mismatch\n");
                std::abort();
            }
#endif
    }

    // Placement + side to move and hands stay separate for dominance-cache keys.
    ZobristKey placement_key;
    ZobristKey hands_key;

    // White occupancy is derived, so only two 16-byte masks are stored.
    Bitboard81 occupied;
    Bitboard81 black_pieces;

    // One 7-bit cell per file: black_count + 10 * white_count.
    // A file has 9 squares, so the cell is at most 90 and cannot carry
    // into its neighbor. All nine cells fit in 63 bits, including duplicates.
    uint64_t pawn_file_counts = 0;

    int pawn_count_on_file(int color, int file) const {
        const unsigned cell = unsigned((pawn_file_counts >> (7 * file)) & 127ULL);
        return int(color ? cell / 10 : cell % 10);
    }
    bool has_pawn_on_file_legacy(int color, int file) const {
        for (int row = 0; row < 9; ++row)
            if (sq[row * 9 + file] == sign(color) * P) return true;
        return false;
    }
    bool has_pawn_on_file(int color, int file) const {
#if TSUME_USE_CACHED_PAWN_FILES
        const bool result = pawn_count_on_file(color, file) != 0;
#if TSUME_VERIFY_PAWN_FILES
        if (result != has_pawn_on_file_legacy(color, file)) {
            std::fprintf(stderr, "Cached/reference pawn-file predicate mismatch\n");
            std::abort();
        }
#endif
        return result;
#else
        return has_pawn_on_file_legacy(color, file);
#endif
    }
    void update_pawn_files(int square, int old_piece, int new_piece) {
        if (old_piece == new_piece) return;
        if (old_piece != P && old_piece != -P && new_piece != P && new_piece != -P) return;
        const int shift = 7 * (square % 9);
        if (old_piece == P) pawn_file_counts -= 1ULL << shift;
        else if (old_piece == -P) pawn_file_counts -= 10ULL << shift;
        if (new_piece == P) pawn_file_counts += 1ULL << shift;
        else if (new_piece == -P) pawn_file_counts += 10ULL << shift;
    }
    void verify_pawn_files() const {
#if TSUME_VERIFY_PAWN_FILES
        int counts[2][9]{};
        for (int square = 0; square < 81; ++square)
            if (sq[square] == P || sq[square] == -P)
                ++counts[color_of(sq[square])][square % 9];
        for (int color = 0; color < 2; ++color)
            for (int file = 0; file < 9; ++file)
                if (pawn_count_on_file(color, file) != counts[color][file]) {
                    std::fprintf(stderr, "Incremental/reference pawn-file count mismatch\n");
                    std::abort();
                }
#endif
    }


    Bitboard81 empty_squares() const {
        return {~occupied.low, (~occupied.high) & ((1ULL << 17) - 1)};
    }

    Bitboard81 pieces_of_color(int color) const {
        if (color == 0) return black_pieces;
        return {occupied.low & ~black_pieces.low,
                occupied.high & ~black_pieces.high};
    }

    void verify_bitboards() const {
#if TSUME_VERIFY_BITBOARDS
        Bitboard81 expected_occupied;
        Bitboard81 expected_black;
        Bitboard81 expected_white;
        // Reconstruct independently from the authoritative square array.
        for (int square = 0; square < 81; ++square) {
            if (sq[square] == 0) continue;
            const uint64_t mask = 1ULL << (square % 64);
            uint64_t& all_word = square < 64 ? expected_occupied.low : expected_occupied.high;
            all_word |= mask;
            Bitboard81& color_mask = sq[square] > 0 ? expected_black : expected_white;
            uint64_t& color_word = square < 64 ? color_mask.low : color_mask.high;
            color_word |= mask;
        }
        if (!(occupied == expected_occupied)
            || !(black_pieces == expected_black)
            || !(pieces_of_color(1) == expected_white)) {
            std::fprintf(stderr, "Incremental bitboard/array mismatch\n");
            std::abort();
        }
#endif
    }

    ZobristKey recompute_placement_key() const {
        const auto& tables = ZobristTables::get();
        ZobristKey result;
        for (int square = 0; square < 81; ++square)
            result.xor_with(tables.squares[square][sq[square] + 14]);
        if (turn == 1) result.xor_with(tables.white_turn);
        return result;
    }

    ZobristKey recompute_hands_key() const {
        const auto& tables = ZobristTables::get();
        ZobristKey result;
        for (int color = 0; color < 2; ++color)
            for (int piece = P; piece < K; ++piece)
                result.xor_with(tables.hand_key(color, piece, hand[color][piece]));
        return result;
    }

    void verify_zobrist() const {
#if TSUME_VERIFY_ZOBRIST
        if (!(placement_key == recompute_placement_key())
            || !(hands_key == recompute_hands_key())) {
            std::fprintf(stderr, "Zobrist incremental/recomputed mismatch\n");
            std::abort();
        }
#endif
    }

    void set_square(int square, int piece) {
        const int old_piece = sq[square];
        const auto& keys = ZobristTables::get().squares[square];
        placement_key.xor_with(keys[old_piece + 14]);
        placement_key.xor_with(keys[piece + 14]);
        sq[square] = piece;
        update_pawn_files(square, old_piece, piece);
        verify_pawn_files();
        update_king_cache(square, old_piece, piece);
        verify_king_cache();
        occupied.set(square, piece != 0);
        black_pieces.set(square, piece > 0);
        verify_bitboards();
        verify_zobrist();
    }

    void set_hand_count(int color, int piece, int count) {
        if (piece >= P && piece < K) {
            const auto& tables = ZobristTables::get();
            hands_key.xor_with(tables.hand_key(color, piece, hand[color][piece]));
            hands_key.xor_with(tables.hand_key(color, piece, count));
        }
        hand[color][piece] = count;
        verify_zobrist();
    }

    void set_turn(int color) {
        if (int(turn) != color)
            placement_key.xor_with(ZobristTables::get().white_turn);
        turn = color;
        verify_zobrist();
    }
    int king_legacy(int color) const {
        for (int square = 0; square < 81; ++square)
            if (sq[square] == sign(color) * K) return square;
        return -1;
    }
    int king(int color) const {
#if TSUME_USE_CACHED_KINGS
#if TSUME_VERIFY_KING_CACHE
        verify_king_cache();
#endif
        return cached_king(color);
#else
        return king_legacy(color);
#endif
    }
    void add(int c,int p,int n=1) {
        if(p==K) return;
        if(!hand[c][p]) order[c].push_back(p);
        set_hand_count(c, p, hand[c][p] + n);
    }
    void remove(int c,int p) {
        set_hand_count(c, p, hand[c][p] - 1);
        if(hand[c][p]==0) {
            order[c].erase_value(p);
        }
    }
    static Board parse(const std::string& sfen) {
        Board b;std::istringstream in(sfen);std::string rows,t,h;
        if(!(in>>rows>>t>>h)||(t!="b"&&t!="w"))throw std::invalid_argument("Invalid SFEN fields");
        int s=0,r=0,f=0;bool prom=false;
        for(char ch:rows) {
            if(ch=='/') {if(f!=9||prom)throw std::invalid_argument("Invalid SFEN rank");++r;f=0;continue;}
            if(ch=='+') {if(prom)throw std::invalid_argument("Invalid promotion");prom=true;continue;}
            if(ch>='1'&&ch<='9') {if(prom)throw std::invalid_argument("Invalid promotion");f+=ch-'0';continue;}
            int c=ch>='a'&&ch<='z';char u=char(c?ch-'a'+'A':ch);
            const char* p=std::strchr(symbols,u);
            if(!p||p==symbols||r>=9||f>=9)throw std::invalid_argument("Invalid SFEN piece");
            int pt=int(p-symbols);
            if(prom) {pt=promoted[pt];if(!pt)throw std::invalid_argument("Invalid promoted piece");}
            b.set_square(r*9+f++, sign(c)*pt);prom=false;
        }
        (void)s;
        if(r!=8||f!=9||prom)throw std::invalid_argument("Invalid SFEN board");
        b.set_turn(t=="w");int count=0;
        if(h!="-") for(char ch:h) {
            if(ch>='0'&&ch<='9') {count=count*10+ch-'0';if(count>1000)throw std::invalid_argument("Invalid hand count");continue;}
            int c=ch>='a'&&ch<='z';char u=char(c?ch-'a'+'A':ch);const char* p=std::strchr(symbols,u);
            if(!p||p==symbols||p-symbols>=K)throw std::invalid_argument("Invalid hand piece");
            b.add(c,int(p-symbols),count?count:1);count=0;
        }
        if(count)throw std::invalid_argument("Invalid hand count");
        return b;
    }
    std::string sfen() const {
        std::string out;
        for(int r=0;r<9;++r) {
            if(r)out+='/';int empty=0;
            for(int f=0;f<9;++f) {
                int v=sq[r*9+f];if(!v){++empty;continue;}
                if(empty){out+=char('0'+empty);empty=0;}
                int pt=std::abs(v);if(pt>=9)out+='+';
                char ch=symbols[base(pt)];out+=char(v<0?ch-'A'+'a':ch);
            }
            if(empty)out+=char('0'+empty);
        }
        out+=turn?" w ":" b ";std::string h;
        for(int c=0;c<2;++c)for(int p:{R,B,G,S,N,L,P})if(hand[c][p]) {
            if(hand[c][p]>1)h+=std::to_string(hand[c][p]);
            h+=char(c?symbols[p]-'A'+'a':symbols[p]);
        }
        return out+(h.empty()?"-":h)+" 1";
    }
    Bitboard81 attack_mask(int piece, int from, int color) const {
#if TSUME_USE_STEP_ATTACKS
        const int kind = StepAttackTables::slot(piece);
        if (kind >= 0) return StepAttackTables::get().masks[color][kind][from];
#endif
#if TSUME_USE_SLIDER_MAGIC
        if (piece == L || piece == B || piece == R || piece == 13 || piece == 14)
            return SliderMagicTables::get().lookup(piece, from, color, occupied);
#endif
        Bitboard81 result;
        for (int to = 0; to < 81; ++to)
            if (attacks_legacy(piece, from, to, color)) result.set(to, true);
        return result;
    }

    bool attacks(int pt, int from, int to, int color) const {
        if (from == to || from < 0 || to < 0) return false;
#if TSUME_USE_STEP_ATTACKS
        const int kind = StepAttackTables::slot(pt);
        if (kind >= 0) {
            const bool result = StepAttackTables::get().masks[color][kind][from].contains(to);
#if TSUME_VERIFY_ATTACKS
            if (result != attacks_legacy(pt, from, to, color)) {
                std::fprintf(stderr, "Fixed attack table/reference mismatch\n");
                std::abort();
            }
#endif
            return result;
        }
#endif
#if TSUME_USE_SLIDER_MAGIC
        if (pt == L || pt == B || pt == R || pt == 13 || pt == 14) {
            const bool result = SliderMagicTables::get().lookup(pt, from, color, occupied).contains(to);
#if TSUME_VERIFY_ATTACKS
            if (result != attacks_legacy(pt, from, to, color)) {
                std::fprintf(stderr, "Slider magic/reference mismatch\n");
                std::abort();
            }
#endif
            return result;
        }
#endif
        return attacks_legacy(pt, from, to, color);
    }

    bool attacks_legacy(int pt,int from,int to,int c) const {
        if(from==to||from<0||to<0)return false;
        static const struct Tb{signed char r[81],f[81];Tb(){for(int i=0;i<81;++i){r[i]=(signed char)(i/9);f[i]=(signed char)(i%9);}}} tb;
        int dr=tb.r[to]-tb.r[from],df=tb.f[to]-tb.f[from],forward=c?dr:-dr;
        int ar=dr<0?-dr:dr,af=df<0?-df:df;bool ray=false;
        switch(pt) {
        case P:return forward==1&&df==0;
        case L:ray=forward>0&&df==0;break;
        case N:return forward==2&&af==1;
        case S:return (forward==1&&af<=1)||(forward==-1&&af==1);
        case G:case 9:case 10:case 11:case 12:
            return (forward==1&&af<=1)||(dr==0&&af==1)||(forward==-1&&df==0);
        case K:return ar<=1&&af<=1;
        case B:ray=ar==af;break;
        case R:ray=dr==0||df==0;break;
        case 13:if(ar+af==1)return true;ray=ar==af;break;
        case 14:if(ar==1&&af==1)return true;ray=dr==0||df==0;break;
        }
        if(!ray)return false;
        int step=((dr>0)-(dr<0))*9+((df>0)-(df<0));
        for(int i=from+step;i!=to;i+=step)
            if(sq[i])return false;
        return true;
    }
    bool attacked(int color, int target, bool no_king=false) const {
        if (target < 0) return false;
#if TSUME_USE_BITBOARD_ATTACKED
        const bool result = attacked_bitboard(color, target, no_king);
#if TSUME_VERIFY_ATTACKS
        if (result != attacked_legacy(color, target, no_king)) {
            std::fprintf(stderr, "Bitboard/reference attacked-square mismatch\n");
            std::abort();
        }
#endif
        return result;
#else
        return attacked_legacy(color, target, no_king);
#endif
    }

    Bitboard81 visible_ray_candidates(int color, int target) const {
#if TSUME_USE_DIRECT_RAY_CHECKS && TSUME_USE_SLIDER_MAGIC
        auto candidates = SliderMagicTables::get().queen_rays(target,occupied);
#else
        auto candidates = attack_mask(R,target,color);
        const auto diagonals = attack_mask(B,target,color);
        candidates.low |= diagonals.low;
        candidates.high |= diagonals.high;
#endif
        candidates.intersect(pieces_of_color(color));
        return candidates;
    }

    // Precondition: from is the first occupied square on one of target's
    // eight queen rays. Visibility is already established by the ray mask;
    // slider validation needs direction/step shape only, not another lookup.
    bool visible_candidate_attacks(int piece, int from, int target, int color) const {
#if TSUME_USE_DIRECT_RAY_CHECKS
        if (from == target) return false;
        if (piece == L || piece == B || piece == R || piece == 13 || piece == 14) {
            const int dr = target / 9 - from / 9, df = target % 9 - from % 9;
            const bool straight = dr == 0 || df == 0;
            const bool diagonal = dr == df || dr == -df;
            switch (piece) {
            case L: return df == 0 && (color ? dr > 0 : dr < 0);
            case B: return diagonal;
            case R: return straight;
            case 13: return diagonal || std::abs(dr) + std::abs(df) == 1;
            case 14: return straight || (std::abs(dr) == 1 && std::abs(df) == 1);
            }
        }
#endif
        return attacks(piece,from,target,color);
    }

    bool attacked_bitboard(int color, int target, bool no_king) const {
        // From the target, rook and bishop rays reach the nearest blocker in
        // each direction. Every non-knight attacker must be one of these pieces.
        Bitboard81 candidates = visible_ray_candidates(color,target);
        const Bitboard81 friendly = pieces_of_color(color);
        for (int from = candidates.pop_first(); from >= 0; from = candidates.pop_first()) {
            const int piece = std::abs(sq[from]);
            if (no_king && piece == K) continue;
            if (visible_candidate_attacks(piece,from,target,color)) return true;
        }
        // Knights jump over blockers. Reverse the side to find their origins.
        Bitboard81 knights = attack_mask(N, target, 1 - color);
        knights.intersect(friendly);
        for (int from = knights.pop_first(); from >= 0; from = knights.pop_first())
            if (std::abs(sq[from]) == N) return true;
        return false;
    }

    Bitboard81 attackers_legacy(int color, int target, bool no_king=false) const {
        Bitboard81 result;
        if (target < 0) return result;
        for (int from = 0; from < 81; ++from)
            if (sq[from] && color_of(sq[from]) == color
                && (!no_king || std::abs(sq[from]) != K)
                && attacks_legacy(std::abs(sq[from]), from, target, color))
                result.set(from, true);
        return result;
    }

    Bitboard81 attackers(int color, int target, bool no_king=false) const {
#if TSUME_USE_BITBOARD_CHECKERS
        Bitboard81 result;
        if (target < 0) return result;
        Bitboard81 candidates = visible_ray_candidates(color,target);
        const auto friendly = pieces_of_color(color);
        for (int from = candidates.pop_first(); from >= 0; from = candidates.pop_first()) {
            const int piece = std::abs(sq[from]);
            if ((!no_king || piece != K) && visible_candidate_attacks(piece,from,target,color))
                result.set(from, true);
        }
        Bitboard81 knights = attack_mask(N, target, 1 - color);
        knights.intersect(friendly);
        for (int from = knights.pop_first(); from >= 0; from = knights.pop_first())
            if (std::abs(sq[from]) == N) result.set(from, true);
#if TSUME_VERIFY_ATTACKS
        if (!(result == attackers_legacy(color, target, no_king))) {
            std::fprintf(stderr, "Bitboard/reference attacking pieces mismatch\n");
            std::abort();
        }
#endif
        return result;
#else
        return attackers_legacy(color, target, no_king);
#endif
    }

    Bitboard81 interposition_mask(int king, int checker) const {
        if (checker < 0 || checker >= 81) return {};
        const int piece = std::abs(sq[checker]);
        if (!(piece == L || piece == B || piece == R || piece == 13 || piece == 14)) return {};
        const auto result = between_squares(king, checker);
#if TSUME_VERIFY_ATTACKS
        if (!(result == between_squares_legacy(king, checker))) {
            std::fprintf(stderr, "Between-square table/reference mismatch\n");
            std::abort();
        }
#endif
        return result;
    }

    // Preserve the old full-board scan's count and last (highest) source square.
    int count_attackers(int color, int target, int& last) const {
        auto sources = attackers(color, target);
        int count = 0;
        last = -1;
        for (int from = sources.pop_first(); from >= 0; from = sources.pop_first()) {
            last = from;
            ++count;
        }
        return count;
    }

    bool attacked_legacy(int c,int target,bool no_king=false) const {
        if(target<0)return false;
        static const int DR[8]={-1,-1,-1,0,0,1,1,1},DF[8]={-1,0,1,-1,1,-1,0,1};
        int tr=target/9,tf=target%9;
        for(int d=0;d<8;++d) {
            int r=tr+DR[d],f=tf+DF[d];
            while(r>=0&&r<9&&f>=0&&f<9) {
                int v=sq[r*9+f];
                if(v) {
                    if(color_of(v)==c&&(!no_king||std::abs(v)!=K)&&attacks(std::abs(v),r*9+f,target,c))return true;
                    break;
                }
                r+=DR[d];f+=DF[d];
            }
        }
        int kr=tr-(c?2:-2);
        if(kr>=0&&kr<9) {
            for(int df=-1;df<=1;df+=2) {
                int f=tf+df;
                if(f>=0&&f<9&&sq[kr*9+f]==sign(c)*N)return true;
            }
        }
        return false;
    }
    bool check() const {return attacked(1-turn,king(turn));}
    void push(const Move& m) {
        if(m.from<0) {remove(turn,m.drop);set_square(m.to, sign(turn)*m.drop);}
        else {
            if(sq[m.to])add(turn,base(std::abs(sq[m.to])));
            int pt=std::abs(sq[m.from]);set_square(m.from, 0);
            set_square(m.to, sign(turn)*(m.promotion?promoted[pt]:pt));
        }
        set_turn(turn ^ 1);
    }
    bool pseudo(const Move& m) const {
        if(m.to<0||m.to>=81||(sq[m.to]&&color_of(sq[m.to])==int(turn)))return false;
        if(m.from>=0) {
            if(m.from>=81||!sq[m.from]||color_of(sq[m.from])!=int(turn))return false;
            int pt=std::abs(sq[m.from]);
            if(m.promotion&&(!promoted[pt]||(!zone(m.from,turn)&&!zone(m.to,turn))))return false;
            return (m.promotion||mobile(pt,m.to,turn))&&attacks(pt,m.from,m.to,turn);
        }
        // Drops cannot capture an opposing piece. Board moves were handled above.
        if (sq[m.to]) return false;
        if(m.drop<P||m.drop>=K||m.promotion||!hand[turn][m.drop]||!mobile(m.drop,m.to,turn))return false;
        if(m.drop==P && has_pawn_on_file(turn, m.to%9))return false;
        return true;
    }
    // Fast legal(): temporarily edits sq and restores it (no Board copy). Same result as before.
    struct Undo {Board* b;int from,to,fv,tv;
        ~Undo(){if(from>=0)b->set_square(from, fv);b->set_square(to, tv);}};
    bool legal(const Move& m,int kk=-2) const {
        if(!pseudo(m))return false;
        return legal_body(m,kk);
    }
    // For moves produced by board_moves(turn): only the mobility test of pseudo() is still needed.
    // 玉方(後手)の局面で、盤上の駒を動かす応手（合法手）を集める。王手がかかっているときは、応手になりえない手
    // （玉以外で、行き先が「王手の駒の升」でも「間の升」でもない手）を、重い合法判定の前に捨てる。
    // 結果と並び順は、board_moves(1)の全部をlegal_bmにかけた場合と同じ。
    static bool& evfilter_on(){static bool on=true;return on;}
    void defender_legal_moves(std::vector<Move>& out, int mode=0) const {
#if TSUME_USE_BITBOARD_EVASIONS
#if TSUME_VERIFY_MOVES
        const size_t start = out.size();
#endif
        defender_legal_moves_impl<true>(out, mode);
#if TSUME_VERIFY_MOVES
        std::vector<Move> expected;
        defender_legal_moves_impl<false>(expected, mode);
        bool matches = out.size() - start == expected.size();
        for (size_t index = 0; matches && index < expected.size(); ++index) {
            const auto& actual = out[start + index];
            const auto& reference = expected[index];
            matches = actual.from == reference.from && actual.to == reference.to
                && actual.drop == reference.drop && actual.promotion == reference.promotion;
        }
        if (!matches) {
            std::fprintf(stderr, "Bitboard/reference defender list or ordering mismatch\n");
            std::abort();
        }
#endif
#else
        defender_legal_moves_impl<false>(out, mode);
#endif
    }

    template<bool use_bitboards>
    void defender_legal_moves_impl(std::vector<Move>& out, int mode) const {
        bool use=false;bool mask[81];Bitboard81 allowed;int ap[48];int na=0;int kpos=-1;
        if(evfilter_on()){
            int k=king(1);
            if(k>=0){
                int a=-1,count=0;kpos=k;
                count = count_attackers(0, k, a);
                if(count>=1){
                    use=true;std::fill(mask,mask+81,false);
                    if(count==1){
                        allowed = interposition_mask(k, a);
                        allowed.set(a, true);
                        auto squares = allowed;
                        for (int square = squares.pop_first(); square >= 0; square = squares.pop_first())
                            mask[square] = true;
                    }
                }
            }
        }
        if(!use||!direct_on()) {
            for(auto m:board_moves(1)){
                if(use&&std::abs(sq[m.from])!=K&&!mask[m.to])continue;
                if(legal_bm(m))out.push_back(m);
            }
            return;
        }
        // 応手になりうる手を、最初から直接作る（全部の手を作って捨てない）。並び順は board_moves と同じ（移動元の升→行き先の升→不成→成）。
        // Move は初期値つきなので、Move cand[512] と書くと呼ぶたびに512個ぶん初期化されて遅い。使う分だけ書き込む未初期化の領域にする
        alignas(Move) unsigned char cand_buf[512*sizeof(Move)];Move* cand=reinterpret_cast<Move*>(cand_buf);
        bool sure[512];int nc=0;
        (void)ap;(void)na;
        const bool tab=kingtab_on();
        bool ksafe[81];
        if(tab) {   // 玉の移動先ごとに、攻め方の駒の利きが届くかを先に調べる。玉を盤から外した状態で調べる（玉の裏側にも利きが通るため）。他の駒の手を作る前に、必ず元に戻す
            Board* self=const_cast<Board*>(this);int kvsave=sq[kpos];self->set_square(kpos, 0);
            int kr=kpos/9,kf=kpos%9;
            for(int dr=-1;dr<=1;++dr)for(int df=-1;df<=1;++df) {
                if(!dr&&!df)continue;
                int r=kr+dr,f=kf+df;if(r<0||r>=9||f<0||f>=9)continue;
                int t=r*9+f;
                ksafe[t]=!attacked(0,t);   // 攻め方の駒の利きが届くか（玉は盤から外してある）。t上の駒は見ない
            }
            self->set_square(kpos, kvsave);
            if(mode==1) {   // 玉が安全に動ける升が1つでもあれば、それで十分（応手あり）。無ければ何も返さない
                for(int dr=-1;dr<=1;++dr)for(int df=-1;df<=1;++df) {
                    if(!dr&&!df)continue;
                    int r=kr+dr,f=kf+df;if(r<0||r>=9||f<0||f>=9)continue;
                    int t=r*9+f;if(sq[t]&&color_of(sq[t])==1)continue;
                    if(ksafe[t]){out.push_back({kpos,t,0,false});return;}
                }
                return;
            }
        }
        if constexpr (use_bitboards) {
            const Bitboard81 friendly = pieces_of_color(1);
            Bitboard81 sources = friendly;
            for (int from = sources.pop_first(); from >= 0; from = sources.pop_first()) {
                const int piece = std::abs(sq[from]);
                Bitboard81 targets = attack_mask(piece, from, 1);
                targets.exclude(friendly);
                if (piece != K) targets.intersect(allowed);
                for (int to = targets.pop_first(); to >= 0; to = targets.pop_first()) {
                    if (piece == K && tab) {
                        if (!ksafe[to]) continue;
                        sure[nc] = true;
                    } else {
                        sure[nc] = false;
                    }
                    cand[nc++] = {from, to, 0, false};
                    if (promoted[piece] && (zone(from, 1) || zone(to, 1))) {
                        sure[nc] = false;
                        cand[nc++] = {from, to, 0, true};
                    }
                }
            }
        } else {
        int msq[81],nmask=0;for(int t=0;t<81;++t)if(mask[t])msq[nmask++]=t;   // 応手になりうる行き先の升（小さい順）
        for(int s=0;s<81;++s) {
            if(!sq[s]||color_of(sq[s])!=1)continue;
            int pt=std::abs(sq[s]);
            if(pt==K) {
                int sr=s/9,sf=s%9;
                for(int dr=-1;dr<=1;++dr)for(int df=-1;df<=1;++df) {
                    if(!dr&&!df)continue;
                    int r=sr+dr,f=sf+df;if(r<0||r>=9||f<0||f>=9)continue;
                    int t=r*9+f;if(sq[t]&&color_of(sq[t])==1)continue;
                    if(tab) {   // 攻め方の駒の利きが届く升には動けない。届かなければ、そのまま合法
                        if(!ksafe[t])continue;
                        sure[nc]=true;
                    } else sure[nc]=false;
                    cand[nc++]={s,t,0,false};
                }
            } else {
                for(int mi=0;mi<nmask;++mi) {
                    int t=msq[mi];
                    if(sq[t]&&color_of(sq[t])==1)continue;
                    if(!attacks(pt,s,t,1))continue;
                    sure[nc]=false;cand[nc++]={s,t,0,false};
                    if(promoted[pt]&&(zone(s,1)||zone(t,1))){sure[nc]=false;cand[nc++]={s,t,0,true};}
                }
            }
        }
        }
        for(int i=0;i<nc;++i)if(sure[i]||legal_bm(cand[i],kpos))out.push_back(cand[i]);
    }
    static bool& kingtab_on(){static bool on=true;return on;}
    static bool& direct_on(){static bool on=true;return on;}
    bool legal_bm(const Move& m,int kk=-2) const {
        if(!m.promotion&&!mobile(std::abs(sq[m.from]),m.to,turn))return false;
        return legal_body(m,kk);
    }
    // kk: 動かす側の玉の（指す前の）升。-2なら自分で探す。呼び出し側が知っているときは、毎回81升を探さずに済む
    bool legal_body(const Move& m,int kk=-2) const {
        Board* self=const_cast<Board*>(this);
        int mover=turn,opp=turn^1;
        Undo u{self,m.from,m.to,m.from>=0?sq[m.from]:0,sq[m.to]};
        if(m.from<0)self->set_square(m.to, sign(mover)*m.drop);
        else {int pt=std::abs(sq[m.from]);self->set_square(m.to, sign(mover)*(m.promotion?promoted[pt]:pt));self->set_square(m.from, 0);}
        if(attacked(opp,kk==-2?king(mover):(m.from>=0&&m.from==kk?m.to:kk)))return false;
        // 打ち歩詰め（歩を打って詰ますのは反則）。玉が逃げられず、歩を取れる駒（動けないピンされた駒は取れない）も無ければ反則。
        if(m.drop!=P)return true;
        int k=king(opp);
        if(k<0||!attacks(P,m.to,k,mover))return true;
        return pawn_drop_has_reply(mover, k, m.to);
    }

    // Called after a checking pawn has been placed and own-king safety was checked.
    bool pawn_drop_has_reply(int mover, int k, int pawn_square) const {
#if TSUME_USE_BITBOARD_PAWN_DROP
        const bool result = pawn_drop_has_reply_bitboard(mover, k, pawn_square);
#if TSUME_VERIFY_MOVES
        if (result != pawn_drop_has_reply_legacy(mover, k, pawn_square)) {
            std::fprintf(stderr, "Bitboard/reference pawn-drop reply mismatch\n");
            std::abort();
        }
#endif
        return result;
#else
        return pawn_drop_has_reply_legacy(mover, k, pawn_square);
#endif
    }

    bool pawn_drop_has_reply_bitboard(int mover, int k, int pawn_square) const {
        Board* self = const_cast<Board*>(this);
        const int opponent = mover ^ 1;
        // Remove the king before checking destinations so its old square cannot
        // hide a rook/bishop/lance ray. Restore it before enumerating captures.
        const int king_piece = sq[k];
        self->set_square(k, 0);
        auto destinations = attack_mask(K, k, opponent);
        destinations.exclude(pieces_of_color(opponent));
        bool escape = false;
        for (int to = destinations.pop_first(); to >= 0; to = destinations.pop_first()) {
            if (!attacked(mover, to)) {
                escape = true;
                break;
            }
        }
        self->set_square(k, king_piece);
        if (escape) return true;

        // A geometric capturer can be pinned. Make each capture temporarily
        // and retain the historical own-king-safety test, including king lookup.
        auto capturers = attackers(opponent, pawn_square, true);
        for (int from = capturers.pop_first(); from >= 0; from = capturers.pop_first()) {
            const int piece = sq[from], pawn = sq[pawn_square];
            self->set_square(from, 0);
            self->set_square(pawn_square, piece);
            const bool unsafe = attacked(mover, king(opponent));
            self->set_square(from, piece);
            self->set_square(pawn_square, pawn);
            if (!unsafe) return true;
        }
        return false;
    }

    bool pawn_drop_has_reply_legacy(int mover, int k, int pawn_square) const {
        Board* self = const_cast<Board*>(this);
        const int opp = mover ^ 1;
        {   // 玉が動いて逃げられるか（玉自身が元の升から動くので、玉の裏側の利きも考える）
            int kv=sq[k];self->set_square(k, 0);
            bool esc=false;
            for(int s=0;s<81&&!esc;++s)if(attacks(K,k,s,opp)&&(!sq[s]||color_of(sq[s])!=opp))
                if(!attacked(mover,s))esc=true;
            self->set_square(k, kv);
            if(esc)return true;
        }
        // 玉以外の駒が歩を取れるか（取ったあとに自玉が王手になる動き＝ピンされた駒は取れない）
        for(int s=0;s<81;++s) {
            if(!sq[s]||color_of(sq[s])!=opp||std::abs(sq[s])==K)continue;
            if(!attacks(std::abs(sq[s]),s,pawn_square,opp))continue;
            int pv=sq[s],tv=sq[pawn_square];self->set_square(s, 0);self->set_square(pawn_square, pv);
            bool bad=attacked(mover,king(opp));
            self->set_square(s, pv);self->set_square(pawn_square, tv);
            if(!bad)return true;
        }
        return false;
    }
    // True if the move gives check to the opponent king (no Board copy).
    // gives_check と同じだが、玉方の玉の升 k を呼び出し側が渡す（毎回81升を探さない）。
    bool gives_check_k(const Move& m,int k) const {
        Board* self=const_cast<Board*>(this);
        int mover=turn;
        Undo u{self,m.from,m.to,m.from>=0?sq[m.from]:0,sq[m.to]};
        if(m.from<0)self->set_square(m.to, sign(mover)*m.drop);
        else {int pt=std::abs(sq[m.from]);self->set_square(m.to, sign(mover)*(m.promotion?promoted[pt]:pt));self->set_square(m.from, 0);}
        return attacked(mover,k);
    }
    static bool& fastchecks_on(){static bool on=true;return on;}
    bool gives_check(const Move& m) const {
        Board* self=const_cast<Board*>(this);
        int mover=turn;
        Undo u{self,m.from,m.to,m.from>=0?sq[m.from]:0,sq[m.to]};
        if(m.from<0)self->set_square(m.to, sign(mover)*m.drop);
        else {int pt=std::abs(sq[m.from]);self->set_square(m.to, sign(mover)*(m.promotion?promoted[pt]:pt));self->set_square(m.from, 0);}
        return attacked(mover,king(mover^1));
    }
    std::vector<Move> board_moves(int color) const {
#if TSUME_USE_BITBOARD_MOVES
        std::vector<Move> moves;
        moves.reserve(64);
        const Bitboard81 friendly = pieces_of_color(color);
        Bitboard81 sources = friendly;
        for (int from = sources.pop_first(); from >= 0; from = sources.pop_first()) {
            const int piece = std::abs(sq[from]);
            Bitboard81 targets = attack_mask(piece, from, color);
            targets.exclude(friendly);
            for (int to = targets.pop_first(); to >= 0; to = targets.pop_first()) {
                moves.push_back({from, to, 0, false});
                if (promoted[piece] && (zone(from, color) || zone(to, color)))
                    moves.push_back({from, to, 0, true});
            }
        }
#if TSUME_VERIFY_MOVES
        const auto expected = board_moves_legacy(color);
        bool matches = moves.size() == expected.size();
        for (size_t index = 0; matches && index < moves.size(); ++index) {
            const auto& actual = moves[index];
            const auto& reference = expected[index];
            matches = actual.from == reference.from && actual.to == reference.to
                && actual.drop == reference.drop && actual.promotion == reference.promotion;
        }
        if (!matches) {
            std::fprintf(stderr, "Bitboard/reference move list or ordering mismatch\n");
            std::abort();
        }
#endif
        return moves;
#else
        return board_moves_legacy(color);
#endif
    }

    std::vector<Move> board_moves_legacy(int c) const {
        std::vector<Move> out;out.reserve(64);
        const int fw=c?1:-1;
        for(int s=0;s<81;++s)if(sq[s]&&color_of(sq[s])==c) {
            int pt=std::abs(sq[s]);
            bool cand[81];std::fill(cand,cand+81,false);
            int sr=s/9,sf=s%9;
            auto stepto=[&](int dr,int df){int r=sr+dr,f=sf+df;if(r>=0&&r<9&&f>=0&&f<9)cand[r*9+f]=true;};
            auto rayto=[&](int dr,int df){int r=sr+dr,f=sf+df;
                while(r>=0&&r<9&&f>=0&&f<9){cand[r*9+f]=true;if(sq[r*9+f])break;r+=dr;f+=df;}};
            switch(pt) {
            case P:stepto(fw,0);break;
            case L:rayto(fw,0);break;
            case N:stepto(2*fw,-1);stepto(2*fw,1);break;
            case S:stepto(fw,-1);stepto(fw,0);stepto(fw,1);stepto(-fw,-1);stepto(-fw,1);break;
            case G:case 9:case 10:case 11:case 12:
                stepto(fw,-1);stepto(fw,0);stepto(fw,1);stepto(0,-1);stepto(0,1);stepto(-fw,0);break;
            case K:for(int dr=-1;dr<=1;++dr)for(int df=-1;df<=1;++df)if(dr||df)stepto(dr,df);break;
            case B:rayto(-1,-1);rayto(-1,1);rayto(1,-1);rayto(1,1);break;
            case R:rayto(-1,0);rayto(1,0);rayto(0,-1);rayto(0,1);break;
            case 13:rayto(-1,-1);rayto(-1,1);rayto(1,-1);rayto(1,1);
                stepto(-1,0);stepto(1,0);stepto(0,-1);stepto(0,1);break;
            case 14:rayto(-1,0);rayto(1,0);rayto(0,-1);rayto(0,1);
                stepto(-1,-1);stepto(-1,1);stepto(1,-1);stepto(1,1);break;
            }
            for(int t=0;t<81;++t)if(cand[t]&&(!sq[t]||color_of(sq[t])!=c)) {
                out.push_back({s,t,0,false});
                if(promoted[pt]&&(zone(s,c)||zone(t,c)))out.push_back({s,t,0,true});
            }
        }
        return out;
    }
    bool checkmate() const {
        if(!check())return false;
        for(auto m:board_moves(turn))if(legal_bm(m))return false;
#if TSUME_USE_BITBOARD_INVERSE
        auto empty = empty_squares();
        for (int square = empty.pop_first(); square >= 0; square = empty.pop_first())
            for (int piece = P; piece < K; ++piece)
                if (hand[turn][piece] && legal({-1,square,piece,false})) return false;
#else
        for(int s=0;s<81;++s)if(!sq[s])for(int p=P;p<K;++p)
            if(hand[turn][p]&&legal({-1,s,p,false}))return false;
#endif
        return true;
    }
};

struct Pos {
    Board b;
    // Keep dictionary insertion order for inverse move enumeration.
    std::vector<int> order;
    static Pos from(const Board& b) {
        Pos p; p.b = b;
#if TSUME_USE_BITBOARD_INVERSE
        auto occupied = b.occupied;
        for (int square = occupied.pop_first(); square >= 0; square = occupied.pop_first())
            p.order.push_back(square);
#else
        for (int square = 0; square < 81; ++square) if (b.sq[square]) p.order.push_back(square);
#endif
        return p;
    }
    std::array<int,9> remainder() const {
        std::array<int,9> used=b.hand[0],rest{};
#if TSUME_USE_BITBOARD_INVERSE
        auto occupied = b.occupied;
        for (int square = occupied.pop_first(); square >= 0; square = occupied.pop_first()) {
            const int piece = std::abs(b.sq[square]);
            if (piece != K) ++used[base(piece)];
        }
#else
        for(int v:b.sq)if(v&&std::abs(v)!=K)++used[base(std::abs(v))];
#endif
        for(int p=P;p<K;++p)rest[p]=totals[p]-used[p];return rest;
    }
    bool valid() const {auto r=remainder();for(int p=P;p<K;++p)if(r[p]<0)return false;return true;}
    Board board(int turn) const {
        Board q=b;q.set_turn(turn);
        const auto remaining = remainder();
        for (int piece = P; piece < K; ++piece)
            q.set_hand_count(1, piece, remaining[piece]);
        for(int c=0;c<2;++c){q.order[c].clear();for(int p:{R,B,G,S,N,L,P})if(q.hand[c][p])q.order[c].push_back(p);}
        return q;
    }
    void erase(int s){b.set_square(s, 0);order.erase(std::remove(order.begin(),order.end(),s),order.end());}
    void put(int s,int v){if(!b.sq[s])order.push_back(s);b.set_square(s, v);}
    bool dead_ok() const {
#if TSUME_USE_BITBOARD_INVERSE
        auto occupied = b.occupied;
        for (int square = occupied.pop_first(); square >= 0; square = occupied.pop_first())
            if (!mobile(std::abs(b.sq[square]),square,color_of(b.sq[square]))) return false;
#else
        for (int square = 0; square < 81; ++square)
            if (b.sq[square] && !mobile(std::abs(b.sq[square]),square,color_of(b.sq[square]))) return false;
#endif
        return true;
    }
};

struct Timeout {};
struct NodeLimit {};
struct DfpnDepthLimit {};
// 中断用：どのスレッドからでも立てられる。立てると、計算中の探索が次の確認のところで止まる（時間切れと同じ扱い）
static std::atomic<bool> g_cancel{false};
// 128ビットの鍵（局面の見分け用）。64ビットより衝突がずっと少ない。
struct Key128 {uint64_t a,b;bool operator==(const Key128& o) const {return a==o.a&&b==o.b;}};
struct KH {size_t operator()(const Key128& k) const {return size_t(k.a);}};
// 局面表（詰み・不詰・無駄合の記憶）用の高速な表。開番地法（衝突したら隣の升に入れる）。
// 標準のunordered_mapより、実測でメモリが約35%少なく、重い問題で探索が約2割速い。
// 別の表（unordered_denseなど）に替えるときは、下の FastMap の定義だけを書き換える（使う操作は find / [] / end / size / clear の5つ）。
struct BoolMap {
    struct Slot{uint64_t a,bv;};
    Slot* t=nullptr; size_t cap=0,n=0,mask=0;
    struct Found{bool ok;bool second;const Found* operator->()const{return this;}
        bool operator!=(const Found& o)const{return ok!=o.ok;} bool operator==(const Found& o)const{return ok==o.ok;}};
    struct Ref{Slot* s; operator bool()const{return s->bv&1;} bool operator=(bool v){s->bv=(s->bv&~1ULL)|(v?1ULL:0ULL);return v;}};
    BoolMap(){}
    BoolMap(const BoolMap&)=delete; BoolMap& operator=(const BoolMap&)=delete;
    ~BoolMap(){free(t);}
    static inline uint64_t ka(const Key128& k){return k.a|1ULL;}
    static inline uint64_t kb(const Key128& k){return k.b&~1ULL;}
    void rehash(size_t nc){
        Slot* o=t;size_t oc=cap;
        t=(Slot*)calloc(nc,sizeof(Slot));cap=nc;mask=nc-1;
        for(size_t i=0;i<oc;i++) if(o[i].a){size_t j=(o[i].a>>1)&mask;while(t[j].a)j=(j+1)&mask;t[j]=o[i];}
        free(o);
    }
    Found find(const Key128& k)const{
        if(!cap)return Found{false,false};
        uint64_t a=ka(k),b=kb(k);size_t j=(a>>1)&mask;
        while(t[j].a){ if(t[j].a==a&&(t[j].bv&~1ULL)==b)return Found{true,bool(t[j].bv&1)}; j=(j+1)&mask;}
        return Found{false,false};
    }
    Found end()const{return Found{false,false};}
    Ref operator[](const Key128& k){
        if(!cap)rehash(1024);
        else if((n+1)*10>cap*7)rehash(cap*2);
        uint64_t a=ka(k),b=kb(k);size_t j=(a>>1)&mask;
        while(t[j].a){ if(t[j].a==a&&(t[j].bv&~1ULL)==b)return Ref{&t[j]}; j=(j+1)&mask;}
        t[j].a=a;t[j].bv=b;n++;return Ref{&t[j]};
    }
    size_t size()const{return n;}
    void clear(){free(t);t=nullptr;cap=n=mask=0;}
};
// 何も記憶しない表。詰み・不詰の記憶(ca, cd)は、持ち駒の優劣の表(dom)が先に答えるため、ほとんど当たらない（実測で当たり率0.003%〜0.02%）。
// そのためメモリと上限の件数を食うだけになりがちで、既定ではやめている。USE_CA_CD を 1 にすると、従来どおり記憶する。
struct NullMap {
    struct Found{bool ok;bool second;const Found* operator->()const{return this;}
        bool operator!=(const Found& o)const{return ok!=o.ok;} bool operator==(const Found& o)const{return ok==o.ok;}};
    struct Ref{bool v; operator bool()const{return v;} bool operator=(bool x){v=x;return x;}};
    Found find(const Key128&)const{return Found{false,false};}
    Found end()const{return Found{false,false};}
    Ref operator[](const Key128&){return Ref{false};}
    size_t size()const{return 0;}
    void clear(){}
};
using FastMap = BoolMap;      // ← 表の種類を替えるときは、ここを書き換える

static inline uint64_t sm64(uint64_t z){z+=0x9E3779B97F4A7C15ULL;z=(z^(z>>30))*0xBF58476D1CE4E5B9ULL;z=(z^(z>>27))*0x94D049BB133111EBULL;return z^(z>>31);}
static inline Key128 kmix(const Key128& x,uint64_t t){return Key128{sm64(x.a^sm64(t)),sm64(x.b+t*0xD6E8FEB86659FD93ULL+0x1234567ULL)};}
struct Solver {
    #if USE_CA_CD
    FastMap ca,cd;
#else
    NullMap ca,cd;
#endif
    FastMap cf,cb;   // cb: 升ごとの無駄合まとめ判定の結果
    bool batch_on=true;   // 同じ升の合駒を、玉方の持駒を減らさない一番有利な状態で1回だけ判定する（詰めば、その升の全種類が無駄合）
    // Optional oracle: returns 1 (mate under normal rules), -1 (no mate), 0 (unknown). Used only to prune attacker nodes.
    int (*oracle)(const char*)=nullptr;
    std::unordered_map<Key128,int,KH> ost;
    long long o_calls=0,o_pruned=0;
    int oracle_min=5;
    int futile_floor=0;   // 無駄合の判定に使う手数の下限（0=使わない）。浅い探索でも無駄合を見抜くための、短い手数の再確認用
    bool final_alt=false; // allow several last moves (any square) when true
    std::string error;
    std::string last_output;
    std::atomic<bool> context_cancel{false};
    bool timed=false;
    std::chrono::steady_clock::time_point deadline;
    void tick(){if(timed&&(g_cancel.load(std::memory_order_relaxed)||context_cancel.load(std::memory_order_relaxed)||std::chrono::steady_clock::now()>=deadline))throw Timeout{};}
    void clear(){ca.clear();cd.clear();cf.clear();cb.clear();dom[0].clear();dom[1].clear();dom_count=0;chint.clear();dhint.clear();dp_proof_clear();dp_required_defenses.clear();dp_required_count=0;dp_feedback_worker.reset();dpt.clear();dpath.clear();dp_ent=0;dpl_memo.clear();dpl_path.clear();dp_vis.clear();}
    std::unordered_map<Key128,Move,KH> chint,dhint;   // move-ordering hints (do not affect results)
    bool hints_on=false;
    size_t cache_cap=TSUME_CAP;
    // 記憶が上限を超えたとき：作業用の記憶(ca/cd/cf)だけを捨てる。優劣の記憶(dom)と「先に試す手」(chint/dhint)は、
    // 後の手数の確認で効くので残す。dom 自体が上限の半分を超えたときは、従来どおり全部捨てる。
    void trim(){if(ca.size()+cd.size()+cf.size()+dom_count>cache_cap){
        ca.clear();cd.clear();cf.clear();
        if(dom_count>cache_cap/2){ost.clear();dom[0].clear();dom[1].clear();dom_count=0;chint.clear();dhint.clear();}}}
    static uint64_t fnv(const std::string& k,uint64_t h=1469598103934665603ULL){for(unsigned char c:k){h^=c;h*=1099511628211ULL;}h^=h>>29;h*=0xbf58476d1ce4e5b9ULL;h^=h>>32;return h;}
    // Search settings belong to the query, not to the incremental board state.
    Key128 hashboard(const Board& b,int n,bool hands) {
#if TSUME_USE_ZOBRIST
        b.verify_zobrist();
        ZobristKey position = b.placement_key;
        if (hands) position.xor_with(b.hands_key);
        const uint64_t settings = uint64_t(b.turn)
            | (uint64_t(unsigned(n)) << 8)
            | (uint64_t(unsigned(futile_floor) & 255u) << 40)
            | (hands ? (1ULL << 48) : 0);
        const Key128 result = kmix({position.low, position.high}, settings);
#if TSUME_VERIFY_ZOBRIST
        ZobristKey recomputed = b.recompute_placement_key();
        if (hands) recomputed.xor_with(b.recompute_hands_key());
        if (!(result == kmix({recomputed.low, recomputed.high}, settings))) {
            std::fprintf(stderr, "Search key differs from recomputed Zobrist key\n");
            std::abort();
        }
#endif
        return result;
#else
        uint64_t a=0x243F6A8885A308D3ULL,c=0x13198A2E03707344ULL;
        auto mixw=[&](uint64_t w){
            a=(a^w)*0x9E3779B97F4A7C15ULL;a=(a<<27)|(a>>37);a*=0xC2B2AE3D27D4EB4FULL;
            c=(c+w)*0x165667B19E3779F9ULL;c^=c>>29;c=(c<<31)|(c>>33);
        };
        {   // 盤の81升を1升1バイトに詰めてから、8バイトずつ読む（x86はリトルエンディアンなので、1升ずつ8ビットずらして足す元の計算と同じ値になる）
            unsigned char buf[88];
            for(int i=0;i<81;++i)buf[i]=(unsigned char)(b.sq[i]+16);
            for(int i=81;i<88;++i)buf[i]=0;
            for(int i=0;i<81;i+=8){uint64_t w;std::memcpy(&w,buf+i,8);mixw(w);}
        }
        if(hands) {
            for(auto& hh:b.hand){
                uint64_t w=0;int cnt=0;
                for(int p=P;p<K;++p){w|=(uint64_t(hh[p])&0xFFFFu)<<(16*cnt);if(++cnt==4){mixw(w);w=0;cnt=0;}}
                mixw(w);
            }
        }
        mixw(uint64_t(b.turn)|(uint64_t(unsigned(n))<<8)|(uint64_t(unsigned(futile_floor)&255u)<<40)|(hands?(1ULL<<48):0));   // 判定の深さの設定が違えば結果も違うので、鍵に混ぜる
        return Key128{sm64(a),sm64(c^0x5851F42D4C957F2DULL)};
#endif
    }
    Key128 key(const Board& b,int n) {return hashboard(b,n,true);}
    std::vector<Move> checks(const Board& b) {
        tick();
#if TSUME_USE_BITBOARD_CHECKS
        auto out = checks_impl<true>(b);
#if TSUME_VERIFY_MOVES
        const auto reference = checks_impl<false>(b);
        bool matches = out.size() == reference.size();
        for (size_t index = 0; matches && index < out.size(); ++index) {
            const auto& actual = out[index];
            const auto& expected = reference[index];
            matches = actual.from == expected.from && actual.to == expected.to
                && actual.drop == expected.drop && actual.promotion == expected.promotion;
        }
        if (!matches) {
            std::fprintf(stderr, "Bitboard/reference checking move list or ordering mismatch\n");
            std::abort();
        }
#endif
        return out;
#else
        return checks_impl<false>(b);
#endif
    }

    template<bool use_bitboards>
    std::vector<Move> checks_impl(const Board& b) {
        std::vector<Move> out;
        const int k = b.king(1), ak = b.king(0);
        if constexpr (use_bitboards) {
            // Keep historical behavior for inputs outside the attacker-to-move case.
            if (k < 0 || b.turn != 0) return checks_impl<false>(b);
        }
        std::array<Bitboard81, 15> target_masks{};
        bool target_ready[15]{};
        auto checking_targets = [&](int piece) -> const Bitboard81& {
            if (!target_ready[piece]) {
                // Reverse the side: origins of checks become destinations from the king.
                target_masks[piece] = b.attack_mask(piece, k, 1);
                target_ready[piece] = true;
            }
            return target_masks[piece];
        };
        auto append_drop = [&](int piece, int to) {
            Move move{-1, to, piece, false};
            if (!b.legal(move, ak)) return;
            // Retain the existing stricter pawn-drop-mate validation.
            if (piece == P) {
                Board next = b;
                next.push(move);
                if (!has_evasion(next, 0)) return;
            }
            out.push_back(move);
        };
        for (int piece : b.order[0]) if (b.hand[0][piece] > 0) {
            if constexpr (use_bitboards) {
                Bitboard81 targets = checking_targets(piece);
                targets.exclude(b.occupied);
                for (int to = targets.pop_first(); to >= 0; to = targets.pop_first())
                    append_drop(piece, to);
            } else {
                for (int to = 0; to < 81; ++to)
                    if (!b.sq[to] && b.attacks(piece, k, to, 1)) append_drop(piece, to);
            }
        }
        Bitboard81 may_reveal;
        bool filter = false;
        if constexpr (use_bitboards) {
            // An existing check can survive an unrelated move. Do not filter that case.
            filter = !b.attacked(0, k);
            if (filter) {
                may_reveal = checking_targets(R);
                const auto diagonals = checking_targets(B);
                may_reveal.low |= diagonals.low;
                may_reveal.high |= diagonals.high;
                may_reveal.intersect(b.pieces_of_color(0));
            }
        }
        for (auto move : b.board_moves(0)) {
            if constexpr (use_bitboards) {
                const int piece = move.promotion ? promoted[std::abs(b.sq[move.from])]
                                                 : std::abs(b.sq[move.from]);
                // Retain all moves of the first own blocker on each king ray:
                // moving it can uncover a check or extend its own slider ray.
                // Capturing the king is left to the historical validation as well.
                if (filter && move.to != k && !may_reveal.contains(move.from)
                    && !checking_targets(piece).contains(move.to)) continue;
            }
            if (Board::fastchecks_on() && ak < 0) {
                if ((move.promotion || mobile(std::abs(b.sq[move.from]), move.to, b.turn))
                    && b.gives_check_k(move, k)) out.push_back(move);
            } else if (b.legal(move, ak) && b.gives_check(move)) {
                out.push_back(move);
            }
        }
        return out;
    }
    std::unordered_set<Key128,KH> inprog;
    int fdepth=0,maxDepth=12;
    // ■無駄合の定義について（この判定は定義の選び方で結果が変わる。詳しくは https://w.atwiki.jp/mudaai/pages/29.html ）
    //  ・棋慧の定義：合駒（打つ合駒・盤上の駒を動かす移動合の両方）を攻め方のどの駒で取ってもよく、
    //    取った合駒は攻め方の持駒として使えないものとして、残りの手数以内に詰むなら無駄合とする。
    //  ・そのため、取った合駒を使わないと詰まない局面では「無駄合ではない」と判定する（手数が長くなることがある）。
    //    例: 7pn/6p2/6B1k/6+B1p/9/6L2/9/9/9 b P2r4g4s3n3l14p 1 の３五香打（取った香で詰ます変化があるため無駄合としない）。
    //  ・取った駒を使ってよいとする流儀とは結果が食い違うことがある。これは不具合ではなく定義の違い。
    // Futile interposition: after the slider captures the dropped piece, remove that piece from the attacker's hand;
    // if mate is still reached within n plies, the drop is futile (n=0: only when no evasion remains).
    // Only replace source-square enumeration. Keep every positive piece,
    // including geometrically impossible captures, for the existing legal() test.
    static Bitboard81 futile_capture_sources(const Board& board, int attacker, bool all_captures=ALLCAP != 0) {
        Bitboard81 sources;
#if TSUME_USE_BITBOARD_FUTILE_CAPTURES
        sources = board.pieces_of_color(0);
        if (!all_captures) {
            Bitboard81 single;
            if (attacker >= 0 && attacker < 81 && sources.contains(attacker)) single.set(attacker, true);
            sources = single;
        }
#else
        for (int from = 0; from < 81; ++from)
            if (board.sq[from] > 0 && (all_captures || from == attacker)) sources.set(from, true);
#endif
#if TSUME_VERIFY_MOVES
        Bitboard81 reference;
        for (int from = 0; from < 81; ++from)
            if (board.sq[from] > 0 && (all_captures || from == attacker)) reference.set(from, true);
        if (!(sources == reference)) {
            std::fprintf(stderr, "Bitboard/reference futility capture sources mismatch\n");
            std::abort();
        }
#endif
        return sources;
    }

    bool futile(const Board& b,const Move& d,int a,int n=0) {
        if(n>=1&&n<futile_floor)n=futile_floor;
        Key128 k=kmix(key(b,n),uint64_t(d.to+1)*131+uint64_t(d.drop)*17+(d.from<0?7:uint64_t(d.from)*257)+(d.promotion?3:0));auto it=cf.find(k);if(it!=cf.end())return it->second;
        if(inprog.count(k))return false;
        const int rem=d.from<0?d.drop:base(std::abs(b.sq[d.from]));   // 合駒になった駒の種類（移動合も同じ扱い）
        bool wide=n>=1&&fdepth<maxDepth;
        if(wide){inprog.insert(k);++fdepth;}
        bool res=false;
        try {
            Board q=b;q.push(d);
            // 合駒は、王手をかけている駒（a）だけでなく、攻め方のどの駒で取ってもよい（他の駒で取れば詰む場合も無駄合）　26/11/03
            // restore=true: 合駒に使った駒を玉方の持駒に戻した（一番有利な）状態で判定する。これで詰めば、どの種類の合駒でも詰むので、その升の全種類が無駄合になる。
            const int qk0=q.king(0);
            auto caps=[&](bool restore)->bool{
                auto sources = futile_capture_sources(q, a);
                for (int from = sources.pop_first(); from >= 0; from = sources.pop_first()) {
                    for(bool prom:{false,true}) {Move m{from,d.to,0,prom};if(!q.legal(m,qk0))continue;
                        Board r=q;r.push(m);if(!r.check())continue;
                        if(!wide){if(!has_evasion(r,0))return true;}
                        else {r.remove(0,rem);if(restore)r.add(1,d.drop);if(defenders(r,n))return true;}
                    }
                }
                return false;
            };
            if(wide&&batch_on&&d.from<0) {
                Key128 kb=kmix(key(b,n),uint64_t(d.to+1)*7919+13);
                auto ib=cb.find(kb);
                if(ib!=cb.end())res=ib->second;
                else if(!inprog.count(kb)) {
                    inprog.insert(kb);bool br=false;
                    try{br=caps(true);}catch(...){inprog.erase(kb);throw;}
                    inprog.erase(kb);cb[kb]=br;res=br;
                }
            }
            if(!res)res=caps(false);
        } catch(...) {if(wide){inprog.erase(k);--fdepth;}throw;}
        if(wide){inprog.erase(k);--fdepth;}
        cf[k]=res;return res;
    }
    // 王手が離れた駒1枚だけ、かつ間に升があるとき、その間の升を返す（移動合・打つ合駒の候補の升）
    static bool is_interp_move(const Board& b,const Move& m,const std::vector<int>& sqs) {
        if(m.from<0||std::abs(b.sq[m.from])==K)return false;
        for(int q:sqs)if(q==m.to)return true;
        return false;
    }
    // 王手が遠隔駒1枚だけで間に升があるとき、王手駒の位置 a と間の升を返す
    static bool interp_squares(const Board& b,int& a,std::vector<int>& sqs) {
        int k=b.king(1),count=0;a=-1;
        count = b.count_attackers(0, k, a);
        if(count!=1)return false;
        const auto between = b.interposition_mask(k, a);
        if (between.low == 0 && between.high == 0) return false;
        append_between_squares(between, k, a, sqs);
        return true;
    }
    std::vector<Move> evasions(const Board& b,int bud=0) {
        tick();std::vector<Move> out;
        if(b.turn==1){b.defender_legal_moves(out);}
        else for(auto m:b.board_moves(1))if(b.legal(m))out.push_back(m);
        int a = -1;
        std::vector<int> sqs;
        if (!interp_squares(b, a, sqs)) return out;
        for (int s : sqs) {
            for(int p:b.order[1])if(b.hand[1][p]>0) {
                Move m{-1,s,p,false};if(b.legal(m)&&!futile(b,m,a,bud))out.push_back(m);
            }
        }
        // 盤上の駒を動かす合駒（移動合）も、打つ合駒と同じく無駄合なら受けにならない
        std::vector<Move> kept;
        for(auto& m:out)if(!(is_interp_move(b,m,sqs)&&futile(b,m,a,bud)))kept.push_back(m);
        out.swap(kept);
        return out;
    }
    // Like evasions() but returns interposition drops without testing futility (caller tests lazily).
    void evasions_split(const Board& b,std::vector<Move>& normal,std::vector<Move>& drops,int& att) {
        tick();att=-1;
        if(b.turn==1){b.defender_legal_moves(normal);}
        else for(auto m:b.board_moves(1))if(b.legal(m))normal.push_back(m);
        int a = -1;
        std::vector<int> sqs;
        if (!interp_squares(b, a, sqs)) return;
        {   // 移動合は「打つ合駒」と同じ扱い（無駄合かどうかを後で調べる）
            std::vector<Move> keep;
            for(auto& m:normal){if(is_interp_move(b,m,sqs))drops.push_back(m);else keep.push_back(m);}
            normal.swap(keep);
        }
        for (int s : sqs) {
            for(int p:b.order[1])if(b.hand[1][p]>0) {
                Move m{-1,s,p,false};if(b.legal(m))drops.push_back(m);
            }
        }
        att=a;
    }
    // Same as !evasions(b,bud).empty(), but stops at the first evasion found.
    bool has_evasion(const Board& b,int bud) {
        std::vector<Move> normal,drops;int att;evasions_split(b,normal,drops,att);
        if(!normal.empty())return true;
        for(auto& d:drops)if(!futile(b,d,att,bud))return true;
        return false;
    }
    // Hand-dominance cache: a result for one hand pair also answers positions with a better/worse hand pair.
    struct DomEntry {uint8_t a[7],d[7];int n;bool res;};
    std::unordered_map<Key128,std::vector<DomEntry>,KH> dom[2];
    size_t dom_count=0;
    bool dom_on=true;
    Key128 dom_key(const Board& b,int n) {return hashboard(b,n,false);}
    static constexpr uint16_t DPH_UNKNOWN=65535;
    struct DP{uint64_t pn,dn;bool path_dependent=false;uint16_t height=DPH_UNKNOWN;};
    struct DEnt{uint8_t a[7],d[7];uint16_t height;uint64_t pn,dn;};
    std::unordered_map<Key128,std::vector<DEnt>,KH> dpt;
    std::unordered_set<Key128,KH> dpath;
    // Per-operation visit counts; the Python job monitor adds successive operations.
    void (TSUME_CALL *search_callback)(unsigned long long,double,int)=nullptr;
    unsigned long long search_nodes=0;
    bool search_active=false;
    std::chrono::steady_clock::time_point search_started,search_last;
    void search_publish(bool finished=false) {
        if(!search_active||!search_callback)return;
        const auto now=std::chrono::steady_clock::now();
        if(!finished&&std::chrono::duration<double>(now-search_last).count()<0.2)return;
        search_last=now;
        search_callback(search_nodes,std::chrono::duration<double>(now-search_started).count(),finished?0:1);
    }
    void search_visit() {
        if(search_active){++search_nodes;if((search_nodes&1023)==0)search_publish();}
    }
    struct SearchProgressScope {
        Solver& owner;
        explicit SearchProgressScope(Solver& s):owner(s) {
            if(s.search_callback){s.search_nodes=0;s.search_started=s.search_last=std::chrono::steady_clock::now();s.search_active=true;}
        }
        ~SearchProgressScope(){if(owner.search_nodes)owner.search_publish(true);owner.search_active=false;}
    };
    void (TSUME_CALL *dp_progress_callback)(unsigned long long,double,int)=nullptr;
    unsigned long long dp_progress_nodes=0;
    bool dp_progress_active=false;
    int dp_progress_stage=0;
    double dp_progress_search_seconds=0;
    std::chrono::steady_clock::time_point dp_progress_started,dp_progress_last;
    void dp_progress_publish(bool force=false) {
        if(!dp_progress_active||!dp_progress_callback)return;
        const auto now=std::chrono::steady_clock::now();
        if(!force&&std::chrono::duration<double>(now-dp_progress_last).count()<0.2)return;
        dp_progress_last=now;
        const double seconds=dp_progress_stage==1?std::chrono::duration<double>(now-dp_progress_started).count():dp_progress_search_seconds;
        dp_progress_callback(dp_progress_nodes,seconds,dp_progress_stage);
    }
    void dp_progress_begin() {
        if(!dp_progress_callback)return;
        dp_progress_nodes=0;dp_progress_search_seconds=0;dp_progress_stage=1;
        dp_progress_started=dp_progress_last=std::chrono::steady_clock::now();
        dp_progress_active=true;dp_progress_publish(true);
    }
    void dp_progress_change_stage(int stage) {
        if(!dp_progress_active)return;
        if(dp_progress_stage==1)dp_progress_search_seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-dp_progress_started).count();
        dp_progress_stage=stage;dp_progress_publish(true);
    }
    void dp_progress_end() {if(dp_progress_active){dp_progress_change_stage(0);dp_progress_active=false;}}
    struct DfpnProgressScope {
        Solver& owner;
        explicit DfpnProgressScope(Solver& s):owner(s){owner.dp_progress_begin();}
        ~DfpnProgressScope(){owner.dp_progress_end();}
    };
    long long dp_nodes=0,dp_ent=0,dp_limit=0;
    bool dp_deep=false;  // 深さの上限に達したか
    int dp_max_depth=600;
    bool dp_result_path_dependent=false;  // 根の結論に現在の経路の循環判定を使ったか
    int dp_prune=1;      // 合駒の静的な絞り込み
    int dp_chain=1;      // 合駒を鎖にまとめる
    static constexpr uint64_t DINF=(1ULL<<40);
    static void dp_hands(const Board& b,uint8_t* a,uint8_t* d){for(int i=0;i<7;++i){a[i]=(uint8_t)std::min(255,b.hand[0][i+1]);d[i]=(uint8_t)std::min(255,b.hand[1][i+1]);}}
    bool dp_look(const Board& b,DP& out,bool& exact) {
        exact=false;auto it=dpt.find(dom_key(b,0));if(it==dpt.end())return false;
        uint8_t a[7],d[7];dp_hands(b,a,d);
        for(auto& e:it->second){
            bool same=true;for(int i=0;i<7&&same;++i)same=(e.a[i]==a[i]&&e.d[i]==d[i]);
            if(same){out=DP{e.pn,e.dn,false,e.height};exact=true;return true;}
        }
        for(auto& e:it->second){
            if(e.pn==0){bool ok=true;for(int i=0;i<7&&ok;++i)ok=e.a[i]<=a[i]&&e.d[i]>=d[i];if(ok){out=DP{0,DINF,false,e.height};return true;}}
            else if(e.dn==0){bool ok=true;for(int i=0;i<7&&ok;++i)ok=a[i]<=e.a[i]&&d[i]>=e.d[i];if(ok){out=DP{DINF,0};return true;}}
        }
        return false;
    }
    DP dp_get(const Board& b){DP r;bool ex;if(dp_look(b,r,ex))return r;return DP{1,1};}
    void dp_put(const Board& b,uint64_t pn,uint64_t dn,bool path_dependent=false,uint16_t height=DPH_UNKNOWN) {
        // 現在の祖先に依存した値を、別経路から再利用できる表には入れない。
        if(path_dependent)return;
        auto& v=dpt[dom_key(b,0)];uint8_t a[7],d[7];dp_hands(b,a,d);
        for(auto& e:v){bool same=true;for(int i=0;i<7&&same;++i)same=(e.a[i]==a[i]&&e.d[i]==d[i]);if(same){e.height=pn==0&&e.pn==0?std::min(e.height,height):height;e.pn=pn;e.dn=dn;return;}}
        DEnt e;for(int i=0;i<7;++i){e.a[i]=a[i];e.d[i]=d[i];}e.pn=pn;e.dn=dn;e.height=height;
        if(v.size()>=16){size_t k=0;for(size_t i=0;i<v.size();++i)if(v[i].pn&&v[i].dn){k=i;break;}v.erase(v.begin()+k);--dp_ent;}
        v.push_back(e);++dp_ent;
    }
    // Inclusion constraints are board/turn based and therefore apply uniformly
    // across hand-dominance variants. Numerical caches are cleared on changes.
    Key128 dp_required_key(const Board&b) {
#if TSUME_USE_ZOBRIST
        return kmix({b.placement_key.low,b.placement_key.high},uint64_t(b.turn));
#else
        std::string board;board.reserve(82);board+=char(b.turn);
        for(int sq:b.sq)board+=char(sq+16);
        return {fnv(board),fnv(board,0x9e3779b97f4a7c15ULL)};
#endif
    }
    std::unordered_map<Key128,std::vector<Move>,KH> dp_required_defenses;
    size_t dp_required_count=0;
    bool dp_defense_required(const Board&b,const Move&m) {
        if(dp_required_defenses.empty())return false;
        auto f=dp_required_defenses.find(dp_required_key(b));if(f==dp_required_defenses.end())return false;
        for(const auto&x:f->second)if(x.from==m.from&&x.to==m.to&&x.drop==m.drop&&x.promotion==m.promotion)return true;
        return false;
    }
    struct DItem{Move m;Board q;std::vector<Move> rest;DP local{1,1};bool local_valid=false;};
    DP dp_child_value(const DItem& item) {
        if(dpath.count(key(item.q,0)))return DP{DINF,0,true};
        if(item.local_valid)return item.local;
        return dp_get(item.q);
    }
    static bool dp_contextual_result(bool orn,uint64_t pn,uint64_t dn,
                                     bool any_context,bool clean_mate,bool clean_nomate) {
        // ORの詰みは独立した1枝、ANDの不詰も独立した1枝で確定する。
        // 他の枝に循環があっても、その結論の根拠には含めない。
        if(orn&&pn==0&&clean_mate)return false;
        if(!orn&&dn==0&&clean_nomate)return false;
        return any_context;
    }
    // 玉方の局面で、玉の隣以外の升に合駒をする意味があるか（升に玉方の駒の利きがあるか）
    // Corrected array oracle: piece type is positive, defender color is 1.
    static bool dp_support_reference(const Board& b,int to,int movedfrom) {
        if (to < 0 || to >= 81) return false;
        for (int from = 0; from < 81; ++from)
            if (b.sq[from] < 0 && from != movedfrom && std::abs(b.sq[from]) != K
                && b.attacks_legacy(std::abs(b.sq[from]),from,to,1)) return true;
        return false;
    }
    bool dp_support(const Board& b,int to,int movedfrom) {
        if (to < 0 || to >= 81) return false;
#if TSUME_USE_BITBOARD_SUPPORT
        auto supporters = b.attackers(1,to,true);
        if (movedfrom >= 0 && movedfrom < 81) supporters.set(movedfrom,false);
        const bool result = supporters.low != 0 || supporters.high != 0;
#if TSUME_VERIFY_ATTACKS
        if (result != dp_support_reference(b,to,movedfrom)) {
            std::fprintf(stderr, "Bitboard/reference defender support mismatch\n");
            std::abort();
        }
#endif
        return result;
#else
        return dp_support_reference(b,to,movedfrom);
#endif
    }
    void dp_items(const Board& b,std::vector<DItem>& items,int bud=-1) {
        std::vector<Move> mv;
        if(b.turn==0){mv=checks(b);for(auto&m:mv){DItem it;it.m=m;it.q=b;it.q.push(m);items.push_back(std::move(it));}return;}
        std::vector<Move> normal,drops;int att;evasions_split(b,normal,drops,att);
        for(auto&m:normal){DItem it;it.m=m;it.q=b;it.q.push(m);items.push_back(std::move(it));}
        if(drops.empty())return;
        int k=b.king(1);
        std::vector<Move> dchain,mchain;
        for(auto&m:drops){
            if(bud>=0&&futile(b,m,att,bud))continue;   // 棋慧の厳密な無駄合の判定（残り手数 bud で判定）
            // この静的な省略は持駒を打つ合駒だけに適用する。
            // 移動合は移動元が空いて逆王手などの利きが変わるため、
            // 合駒先の支えの有無だけでは無駄合と判断できない。
            if(bud<0&&dp_prune&&normal.empty()&&m.from<0){
                int dr=m.to/9-k/9,df=m.to%9-k%9;int dist=std::max(std::abs(dr),std::abs(df));
                if(dist>=2&&!dp_support(b,m.to,m.from)&&!dp_defense_required(b,m))continue;
            }
            if(m.from<0)dchain.push_back(m);else mchain.push_back(m);
        }
        auto addchain=[&](std::vector<Move>& ch){
            if(ch.empty())return;
            if(!dp_chain){for(auto&m:ch){DItem it;it.m=m;it.q=b;it.q.push(m);items.push_back(std::move(it));}return;}
            DItem it;it.m=ch[0];it.q=b;it.q.push(ch[0]);
            for(size_t i=1;i<ch.size();++i)it.rest.push_back(ch[i]);
            items.push_back(std::move(it));
        };
        addchain(dchain);addchain(mchain);
    }
    #include "dfpn_proof.h"
    struct NonmateTraceNode { std::string sfen;std::string escape; };
    bool nm_recording=false,nm_truncated=false;
    std::string nm_root;
    std::unordered_map<Key128,NonmateTraceNode,KH> nm_trace;
    void nm_record(const Board&b,const std::vector<DItem>&items) {
        if(!nm_recording)return;
        auto k=key(b,0);
        if(nm_trace.size()>=100000&&nm_trace.find(k)==nm_trace.end()){nm_truncated=true;return;}
        std::string escape;
        if(b.turn==1){
            for(const auto&item:items)if(dp_child_value(item).dn==0){escape=item.m.usi();break;}
            if(escape.empty())return;
        }
        nm_trace[k]=NonmateTraceNode{b.sfen(),escape};
    }
    std::string nm_export() {
        std::string out="{\"root\":"+proof_json_string(nm_root)+",\"truncated\":"+(nm_truncated?"true":"false")+",\"nodes\":[";
        bool comma=false;for(const auto&x:nm_trace){if(comma)out+=',';comma=true;
            out+="{\"sfen\":"+proof_json_string(x.second.sfen)+",\"escape\":"+proof_json_string(x.second.escape)+"}";}
        return out+"]}";
    }
    std::string dfpn_with_nonmate_trace(const Board&b) {
        nm_root=b.sfen();nm_trace.clear();nm_truncated=false;nm_recording=true;
        struct Guard {Solver&s;~Guard(){s.nm_recording=false;}} guard{*this};
        auto out=dfpn_quick(b);
        if(out!="N")nm_trace.clear();
        return out;
    }
    // Exclusions belong to a virtual root only. Never store its restricted
    // proof/disproof under an ordinary position key (including hand dominance).
    bool dp_root_filtered=false;
    std::vector<Move> dp_root_excluded;
    DP dp_filtered_root_value{1,1};
    bool dp_root_allowed(const Move& m) const {
        for(const auto& x:dp_root_excluded)
            if(x.from==m.from&&x.to==m.to&&x.drop==m.drop&&x.promotion==m.promotion)return false;
        return true;
    }
    void dp_mid(const Board& b,uint64_t thpn,uint64_t thdn,uint64_t& rpn,uint64_t& rdn,int depth,
                bool* path_dependent=nullptr,uint16_t* proof_height=nullptr) {
        if(path_dependent)*path_dependent=false;
        if(proof_height)*proof_height=DPH_UNKNOWN;
        tick();search_visit();++dp_nodes;
        if(dp_progress_active){++dp_progress_nodes;if((dp_progress_nodes&1023)==0)dp_progress_publish();}
        if(dp_limit&&dp_nodes>dp_limit)throw NodeLimit{};
        if(dp_ent>dp_cap)throw Timeout{};   // 局面表が大きくなりすぎたら打ち切る（メモリ保護）
        bool orn=(b.turn==0);
        const bool filtered_root=dp_root_filtered&&depth==0;
        std::vector<DItem> items;dp_items(b,items);
        if(filtered_root)items.erase(std::remove_if(items.begin(),items.end(),[&](const DItem& x){return !dp_root_allowed(x.m);}),items.end());
        if(items.empty()){ if(orn){rpn=DINF;rdn=0;}else{rpn=0;rdn=DINF;} const uint16_t h=orn?DPH_UNKNOWN:0;if(filtered_root)dp_filtered_root_value=DP{rpn,rdn,false,h};else dp_put(b,rpn,rdn,false,h);if(proof_height)*proof_height=h;if(!orn&&!filtered_root)dp_record_mate(b,items);if(orn&&!filtered_root)nm_record(b,items);return;}
        // 深さ打切りを不詰の数値に変換しない。未完了として試行を中断する。
        if(depth>dp_max_depth){dp_deep=true;throw DfpnDepthLimit{};}
        Key128 kb=key(b,0);
        if(orn){for(auto&it:items){DP t;bool ex;if(!dp_look(it.q,t,ex)){
                std::vector<DItem> sub;dp_items(it.q,sub);
                if(sub.empty()){dp_put(it.q,0,DINF,false,0);dp_record_mate(it.q,sub);}else dp_put(it.q,(uint64_t)sub.size(),1);}}}
        dpath.insert(kb);
        for(;;) {
            // 鎖の展開：先頭の合駒が詰みと分かったら、次の合駒を別の手として取り出す
            for(size_t i=0;i<items.size();++i){
                while(!items[i].rest.empty()){
                    DP c=dp_child_value(items[i]);if(c.pn!=0)break;
                    DItem nit;nit.m=items[i].rest.front();items[i].rest.erase(items[i].rest.begin());
                    nit.q=b;nit.q.push(nit.m);
                    DP c2=dp_get(nit.q);
                    // 鎖の残りは新しい項目に引き継ぐ
                    nit.rest.swap(items[i].rest);
                    items.push_back(std::move(nit));
                    break;
                }
            }
            uint64_t sumpn=0,sumdn=0,minpn=DINF*4,mindn=DINF*4;
            uint64_t bk=DINF*4,sec=DINF*4;size_t bi=0;uint64_t bdn_=0;
            bool any_context=false,clean_mate=false,clean_nomate=false,all_heights=true;
            uint16_t min_height=DPH_UNKNOWN,max_height=0;
            for(size_t i=0;i<items.size();++i) {
                DP c=dp_child_value(items[i]);
                any_context|=c.path_dependent;
                clean_mate|=c.pn==0&&!c.path_dependent;
                clean_nomate|=c.dn==0&&!c.path_dependent;
                if(c.pn==0&&!c.path_dependent&&c.height!=DPH_UNKNOWN){min_height=std::min(min_height,c.height);max_height=std::max(max_height,c.height);}
                else all_heights=false;
                if(c.pn<minpn)minpn=c.pn; if(c.dn<mindn)mindn=c.dn;
                sumpn=std::min<uint64_t>(DINF,sumpn+c.pn);sumdn=std::min<uint64_t>(DINF,sumdn+c.dn);
                uint64_t k1=orn?c.pn:c.dn;
                if(k1<bk){sec=bk;bk=k1;bi=i;}else if(k1<sec)sec=k1;
            }
            (void)bdn_;
            uint64_t pn,dn;
            if(orn){pn=minpn;dn=sumdn;}else{pn=sumpn;dn=mindn;}
            if(pn>=thpn||dn>=thdn||pn==0||dn==0){
                const bool contextual=dp_contextual_result(orn,pn,dn,any_context,clean_mate,clean_nomate);
                rpn=pn;rdn=dn;if(path_dependent)*path_dependent=contextual;
                uint16_t h=DPH_UNKNOWN;
                if(pn==0&&!contextual){const uint16_t child_height=orn?min_height:(all_heights?max_height:DPH_UNKNOWN);
                    if(child_height<DPH_UNKNOWN-1)h=uint16_t(child_height+1);}
                if(proof_height)*proof_height=h;
                if(filtered_root)dp_filtered_root_value=DP{pn,dn,contextual,h};else dp_put(b,pn,dn,contextual,h);if(pn==0&&!contextual&&!filtered_root)dp_record_mate(b,items);if(dn==0&&!filtered_root)nm_record(b,items);dpath.erase(kb);return;
            }
            DP c=dp_child_value(items[bi]);
            uint64_t cthpn,cthdn;
            uint64_t sc=(sec>=DINF*4?DINF:sec);
            if(orn){
                cthpn=std::min(thpn,sc+1);
                cthdn=(thdn>=DINF)?DINF:(thdn>dn?thdn-dn+c.dn:c.dn+1);
            } else {
                cthdn=std::min(thdn,sc+1);
                cthpn=(thpn>=DINF)?DINF:(thpn>pn?thpn-pn+c.pn:c.pn+1);
            }
            uint64_t cp,cd2;
            Board q=items[bi].q;
            bool child_context=false;uint16_t child_height=DPH_UNKNOWN;
            dp_mid(q,cthpn,cthdn,cp,cd2,depth+1,&child_context,&child_height);
            // 経路依存の子の値は、この親の再帰フレーム内だけで保持する。
            items[bi].local_valid=child_context;
            items[bi].local=DP{cp,cd2,child_context,child_height};
            dp_put(q,cp,cd2,child_context,child_height);
        }
    }
    // df-pn の証明木から手順を作る。攻め方は一番短く詰む手、玉方は一番長く粘る受けを選ぶ
    std::unordered_map<Key128,int,KH> dpl_memo;
    std::unordered_set<Key128,KH> dpl_path;
    static constexpr int DPL_INF=1000000;
    void dp_children(const Board& b,std::vector<std::pair<Move,Board>>& out){
        std::vector<DItem> items;dp_items(b,items);
        for(auto&it:items){
            out.push_back({it.m,it.q});
            for(auto&r:it.rest){Board q=b;q.push(r);out.push_back({r,q});}
        }
    }
    int dp_len(const Board& b,int depth){
        Key128 k=key(b,0);
        auto f=dpl_memo.find(k);if(f!=dpl_memo.end())return f->second;
        if(depth>400||dpl_path.count(k))return DPL_INF;
        std::vector<std::pair<Move,Board>> ch;dp_children(b,ch);
        int best;
        if(b.turn==0){
            best=DPL_INF;
            dpl_path.insert(k);
            for(auto&c:ch){if(dp_get(c.second).pn!=0)continue;int l=dp_len(c.second,depth+1);if(l<DPL_INF&&l+1<best)best=l+1;}
            dpl_path.erase(k);
        } else {
            if(ch.empty())best=0;
            else{
                best=0;dpl_path.insert(k);
                int cnt=0;for(auto&c:ch){if(dp_get(c.second).pn!=0)continue;int l=dp_len(c.second,depth+1);if(l>=DPL_INF)continue;++cnt;if(l+1>best)best=l+1;}if(!cnt)best=DPL_INF;
                dpl_path.erase(k);
            }
        }
        dpl_memo[k]=best;return best;
    }
    DP dp_line_value(const Board&b) {
        DP best{1,1};auto f=dpt.find(dom_key(b,0));if(f==dpt.end())return best;
        uint8_t a[7],d[7];dp_hands(b,a,d);
        for(const auto&e:f->second){if(e.pn!=0||e.height==DPH_UNKNOWN)continue;bool ok=true;
            for(int i=0;i<7&&ok;++i)ok=e.a[i]<=a[i]&&e.d[i]>=d[i];
            if(ok&&(best.pn!=0||e.height<best.height))best=DP{0,DINF,false,e.height};}
        return best;
    }
    int dp_line_choice(const Board&b,const std::vector<std::pair<Move,Board>>&children,uint16_t bound) {
        int pick=-1;uint16_t best=0;
        for(size_t i=0;i<children.size();++i){DP value=dp_line_value(children[i].second);
            if(value.pn!=0||value.height>=bound)continue;
            if(pick<0||(b.turn==0?value.height<best:value.height>best)){pick=int(i);best=value.height;}}
        return pick;
    }
    bool dp_pv_complete=false;
    std::vector<Move> dp_pv(Board b,bool filtered=false) {
        dp_pv_complete=false;std::vector<Move> pv;std::unordered_set<Key128,KH> seen;
        for(int i=0;i<700;++i){tick();if(!seen.insert(key(b,0)).second)break;
            DP parent=filtered&&i==0?dp_filtered_root_value:dp_line_value(b);if(parent.pn!=0||parent.height==DPH_UNKNOWN)break;
            std::vector<std::pair<Move,Board>> children;dp_children(b,children);
            if(filtered&&i==0)children.erase(std::remove_if(children.begin(),children.end(),[&](const std::pair<Move,Board>& x){return !dp_root_allowed(x.first);}),children.end());
            if(children.empty()){dp_pv_complete=b.turn==1&&b.check()&&!has_evasion(b,0);break;}
            if(parent.height==0)break;
            int pick=dp_line_choice(b,children,parent.height);if(pick<0)break;
            if(!b.legal(children[pick].first))break;
            pv.push_back(children[pick].first);b=children[pick].second;
        }
        if(!dp_pv_complete)pv.clear();
        return pv;
    }
    // df-pn の証明を、精密な探索の「先に試す手」として登録する（結果は変わらず、読む順番だけが良くなる）
    std::unordered_set<Key128,KH> dp_vis;
    long long dp_hints=0;
    void dp_fill(const Board& b,int depth) {
        tick();if(depth>300||dp_vis.size()>=10000)return;
        Key128 kb=key(b,0);if(!dp_vis.insert(kb).second)return;
        DP parent=dp_line_value(b);if(parent.pn!=0||parent.height==DPH_UNKNOWN)return;
        std::vector<std::pair<Move,Board>> children;dp_children(b,children);
        if(b.turn==0){int pick=dp_line_choice(b,children,parent.height);
            if(pick>=0){chint[kb]=children[pick].first;++dp_hints;dp_fill(children[pick].second,depth+1);}}
        else for(const auto&child:children){DP value=dp_line_value(child.second);
            if(value.pn==0&&value.height<parent.height)dp_fill(child.second,depth+1);}
    }
    // 設定を順番に切り替えて試す（問題によって得意な設定が違うため）。各回の上限を倍々に増やしながら、
    // 「絞り込み＋鎖」「鎖のみ」「絞り込みのみ」「どちらもなし」を順に試し、最初に結論が出た設定を採用する
    void dp_portfolio(const Board& b,uint64_t& pn,uint64_t& dn){
        static const int modes[4][2]={{1,1},{0,1},{1,0},{0,0}};
        long long lim=250000;
        for(int round=0;;++round,lim*=3){
            for(int m=0;m<4;++m){
                dp_prune=modes[m][0];dp_chain=modes[m][1];
                dpt.clear();dpath.clear();dp_nodes=0;dp_ent=0;dp_deep=false;dp_limit=lim;
                dp_result_path_dependent=false;dp_filtered_root_value=DP{1,1};dp_proof_attempt();if(nm_recording){nm_trace.clear();nm_truncated=false;}
                try{dp_mid(b,DINF,DINF,pn,dn,0,&dp_result_path_dependent);}
                catch(NodeLimit&){dpt.clear();dpath.clear();continue;}
                catch(DfpnDepthLimit&){
                    // 完了した部分の結論と、深さ打切りの不明を混同しない。
                    dpt.clear();dpath.clear();dp_ent=0;pn=dn=1;
                    dp_result_path_dependent=false;
                    if(round>=1){dp_limit=0;return;}
                    continue;
                }
                catch(...){dp_limit=0;dp_prune=1;dp_chain=1;dpt.clear();dpath.clear();throw;}
                if(pn==0||(dn==0&&!dp_deep)){dp_limit=0;return;}   // 結論が出た（このとき局面表と設定はそのまま残す）
                if(dp_deep&&round>=1){dp_limit=0;return;}          // 深さ上限に当たった場合は「不明」で返す
            }
        }
    }
    std::string dfpn_prime(const Board& b) {
        uint64_t pn,dn;
        dp_portfolio(b,pn,dn);
        std::string r="U";
        if(pn==0){
            std::string pvtxt;   // 手順（一例）も一緒に返す。画面の「暫定」表示用。登録する手がかりは変えない
            {auto pv=dp_pv(b,false);if(dp_pv_complete){pvtxt=" "+std::to_string(pv.size())+" ";bool f=true;for(auto m:pv){if(!f)pvtxt+=' ';f=false;pvtxt+=m.usi();}}}
            dpl_memo.clear();dpl_path.clear();dp_vis.clear();dp_hints=0;
            dp_fill(b,0);hints_on=true;
            r="M "+std::to_string(dp_hints)+pvtxt;
        } else if(dn==0&&!dp_deep)r="N";
        dpt.clear();dpath.clear();dpl_memo.clear();dp_vis.clear();dp_prune=1;dp_chain=1;
        return r;
    }
    long long dp_cap=15000000;
    std::string dfpn_quick(const Board& b,bool filtered=false) {
        DfpnProgressScope progress(*this);
        uint64_t pn,dn;
        dp_portfolio(b,pn,dn);
        dp_progress_change_stage(2);
        std::string r;
        if(pn==0){auto pv=dp_pv(b,filtered);r=dp_pv_complete?"M "+std::to_string(pv.size())+" "+[&]{std::string o;for(auto m:pv){if(!o.empty())o+=' ';o+=m.usi();}return o;}():"U";}
        else if(dn==0&&!dp_deep)r="N";else r="U";
        dpt.clear();dpath.clear();dp_prune=1;dp_chain=1;
        return r;
    }

    std::string dfpn_excluding(const Board& b,const std::vector<Move>& excluded) {
        if(b.turn!=0)throw std::invalid_argument("Excluded first moves require attacker to move");
        for(const auto&m:excluded)if(!b.legal(m))throw std::invalid_argument("Excluded move is not legal at root");
        struct Guard {
            Solver& s;
            Guard(Solver& owner,const std::vector<Move>& x):s(owner){s.dp_root_filtered=true;s.dp_root_excluded=x;}
            ~Guard(){s.dp_root_filtered=false;s.dp_root_excluded.clear();s.dp_filtered_root_value=DP{1,1};}
        } guard(*this,excluded);
        return dfpn_quick(b,true);
    }

    #include "dfpn_feedback.h"
    bool dom_get(int w,const Board& b,int n,bool& res) {
        if(!dom_on)return false;
        auto it=dom[w].find(dom_key(b,0));if(it==dom[w].end())return false;
        uint8_t a[7],d[7];
        // attacker is color 0, defender color 1, regardless of whose turn it is
        for(int i=0;i<7;++i){a[i]=(uint8_t)std::min(255,b.hand[0][i+1]);d[i]=(uint8_t)std::min(255,b.hand[1][i+1]);}
        for(auto& e:it->second) {
            if(e.res) {
                bool ok=n>=e.n;for(int i=0;i<7&&ok;++i)ok=e.a[i]<=a[i]&&e.d[i]>=d[i];
                if(ok){res=true;return true;}
            } else {
                bool ok=n<=e.n;for(int i=0;i<7&&ok;++i)ok=a[i]<=e.a[i]&&d[i]>=e.d[i];
                if(ok){res=false;return true;}
            }
        }
        return false;
    }
    void dom_put(int w,const Board& b,int n,bool res) {
        if(!dom_on)return;
        DomEntry e;for(int i=0;i<7;++i){e.a[i]=(uint8_t)std::min(255,b.hand[0][i+1]);e.d[i]=(uint8_t)std::min(255,b.hand[1][i+1]);}
        e.res=res;e.n=n;auto& v=dom[w][dom_key(b,0)];
        // drop entries that the new one makes redundant, keep lists short
        // 新しい記録で十分な（より広く使える）古い記録は消す。消さないと、同じ局面で古い記録が残り続け、件数も実際より多く数えていた
        for(size_t i=0;i<v.size();){const DomEntry& o=v[i];bool red=o.res==res&&(res?o.n>=n:o.n<=n);
            for(int j=0;j<7&&red;++j)red=res?(o.a[j]>=e.a[j]&&o.d[j]<=e.d[j]):(o.a[j]<=e.a[j]&&o.d[j]>=e.d[j]);
            if(red){v.erase(v.begin()+i);--dom_count;}else ++i;}
        if(v.size()>=16){v.erase(v.begin());--dom_count;}
        v.push_back(e);++dom_count;
    }
    bool mate(const Board& b,int n) {
        search_visit();
        bool r;if(dom_get(0,b,n,r))return r;
        r=mate_impl(b,n);dom_put(0,b,n,r);return r;
    }
    bool defenders(const Board& b,int n) {
        search_visit();
        bool r;if(dom_get(1,b,n,r))return r;
        r=defenders_impl(b,n);dom_put(1,b,n,r);return r;
    }
    bool mate_impl(const Board& b,int n) {
        tick();trim();auto k=key(b,n);auto it=ca.find(k);if(it!=ca.end())return it->second;
        if(oracle&&n>=oracle_min&&b.turn==0) {
            auto ok=key(b,0);auto oi=ost.find(ok);int st;
            if(oi!=ost.end())st=oi->second;
            else {++o_calls;st=oracle(b.sfen().c_str());ost[ok]=st;}
            if(st<0){++o_pruned;return ca[k]=false;}
        }
        Key128 hk{0,0};bool have_h=false;Move hm;
        if(hints_on&&n>=3) {
            hk=key(b,0);auto hi=chint.find(hk);
            if(hi!=chint.end()) {
                have_h=true;hm=hi->second;
                Board q=b;q.push(hm);
                if(defenders(q,n-1))return ca[k]=true;
            }
        }
        std::vector<std::pair<size_t,Move>> scored;
        for(auto m:checks(b)) {Board q=b;q.push(m);
            if(n<3) {   // 残り1手：応手の数は並べ替えに使わないので、数えない。玉が安全に逃げられる手が1つでもあれば詰みではない
                if(q.turn==1){std::vector<Move> t;q.defender_legal_moves(t,1);if(t.size()==1&&std::abs(q.sq[t[0].from])==K)continue;}
                if(!has_evasion(q,n-1))return ca[k]=true;
                continue;
            }
            size_t nb=0;if(q.turn==1){std::vector<Move> tmp;q.defender_legal_moves(tmp);nb=tmp.size();}else{for(auto e:q.board_moves(1))if(q.legal(e))++nb;}
            if(nb==0){auto ev=evasions(q,n-1);
                if(ev.empty()){if(hints_on&&n>=3)chint[key(b,0)]=m;return ca[k]=true;}scored.push_back({ev.size(),m});}
            else if(n<3){if(!has_evasion(q,n-1)){if(hints_on&&n>=3)chint[key(b,0)]=m;return ca[k]=true;}}   // 盤上の駒を動かす受けが全部無駄合のときも詰み
            else scored.push_back({nb,m});}
        if(n>=3) {
            if(AORD==0)std::stable_sort(scored.begin(),scored.end(),[](const auto& a,const auto& b){return a.first<b.first;});
            else std::stable_sort(scored.begin(),scored.end(),[&](const auto& x,const auto& y){
                auto sc=[&](const std::pair<size_t,Move>& v){const Move& m=v.second;size_t base=v.first*4;
                    if(AORD==1)return base+(m.from>=0&&b.sq[m.to]?0:2)+(m.from<0?1:0);
                    if(AORD==2)return base+(m.from<0?0:2)+(m.from>=0&&b.sq[m.to]?0:1);
                    return base+(m.from<0?(m.drop==P?1:2):0);};
                return sc(x)<sc(y);});
            for(auto& v:scored){
                if(have_h&&v.second.from==hm.from&&v.second.to==hm.to&&v.second.drop==hm.drop&&v.second.promotion==hm.promotion)continue;
                Board q=b;q.push(v.second);
                if(defenders(q,n-1)){if(hints_on)chint[key(b,0)]=v.second;return ca[k]=true;}}
        }
        return ca[k]=false;
    }
    bool defenders_impl(const Board& b,int n) {
        tick();auto k=key(b,n);auto it=cd.find(k);if(it!=cd.end())return it->second;
        Key128 hk{0,0};
        if(hints_on&&n>=2) {
            hk=key(b,0);auto hi=dhint.find(hk);
            if(hi!=dhint.end()) {
                Move hm=hi->second;Board q=b;q.push(hm);
                if(!mate(q,n-1)) {
                    int at=-1;
                    if(hm.from>=0){std::vector<int> sqs;if(!interp_squares(b,at,sqs)||!is_interp_move(b,hm,sqs))return cd[k]=false;}
                    else {std::vector<int> sqs;interp_squares(b,at,sqs);}
                    if(!futile(b,hm,at,n))return cd[k]=false;
                }
            }
        }
        std::vector<Move> normal,drops;int att;evasions_split(b,normal,drops,att);
        if(n<2) {
            if(!normal.empty())return cd[k]=false;
            for(auto& d:drops)if(!futile(b,d,att,n))return cd[k]=false;
            return cd[k]=true;
        }
        if(ORD==1)std::stable_sort(normal.begin(),normal.end(),[&](const Move& x,const Move& y){
            auto sc=[&](const Move& m){return (b.sq[m.to]?0:2)+(std::abs(b.sq[m.from])==K?0:1);};return sc(x)<sc(y);});
        if(ORD==3)std::stable_sort(normal.begin(),normal.end(),[&](const Move& x,const Move& y){
            auto sc=[&](const Move& m){return b.sq[m.to]?0:(std::abs(b.sq[m.from])==K?1:2);};return sc(x)<sc(y);});
        if(ORD==4||ORD==5){std::stable_sort(normal.begin(),normal.end(),[&](const Move& x,const Move& y){
            auto sc=[&](const Move& m){return (b.sq[m.to]?0:2)+(std::abs(b.sq[m.from])==K?0:1);};return sc(x)<sc(y);});
            std::stable_sort(drops.begin(),drops.end(),[&](const Move& x,const Move& y){return ORD==4?x.drop<y.drop:x.drop>y.drop;});}
        if(ORD==2)std::stable_sort(normal.begin(),normal.end(),[&](const Move& x,const Move& y){
            auto sc=[&](const Move& m){return std::abs(b.sq[m.from])==K?0:1;};return sc(x)<sc(y);});
        for(auto m:normal){Board q=b;q.push(m);if(!mate(q,n-1)){if(hints_on)dhint[key(b,0)]=m;return cd[k]=false;}}
        for(auto& d:drops){Board q=b;q.push(d);
            if(!mate(q,n-1)&&!futile(b,d,att,n)){if(hints_on)dhint[key(b,0)]=d;return cd[k]=false;}}
        return cd[k]=true;
    }
    std::vector<Move> solve(const Board& b,int n) {
        std::vector<Move> out;for(auto m:checks(b)){Board q=b;q.push(m);if(defenders(q,n-1))out.push_back(m);}return out;
    }
    bool exact(const Board& b,int n){return !(n>=3&&mate(b,n-2))&&mate(b,n);}
    bool line(Board b,int n,std::vector<Move>& out) {
        out.clear();int remaining=n;
        while(true) {
            tick();auto wins=solve(b,remaining);
            if(wins.empty()||(wins.size()!=1&&!(final_alt&&remaining==1)))return false;
            Move pk=wins[0];
            if(wins.size()>1){for(auto w:wins){Board q=b;q.push(w);bool e=true;for(int p=P;p<K;++p)if(q.hand[0][p])e=false;if(e){pk=w;break;}}}
            out.push_back(pk);b.push(pk);auto ev=evasions(b,remaining-1);if(ev.empty())return true;
            Move best;bool found=false;int best_len=-1;
            for(auto d:ev){Board q=b;q.push(d);for(int k=1;k<remaining-1;k+=2)if(mate(q,k)) {
                if(k>best_len){best=d;best_len=k;found=true;}break;}}
            if(!found)return false;out.push_back(best);b.push(best);remaining-=2;
        }
    }
    bool verify(const Board& b,int n,std::vector<Move>& out) {
        if(b.check()||!exact(b,n)||!line(b,n,out)||int(out.size())!=n)return false;
        Board q=b;for(auto m:out)q.push(m);for(int p=P;p<K;++p)if(q.hand[0][p])return false;return true;
    }
    std::vector<std::pair<Pos,Move>> unmove(const Pos& p,int mover) {
        tick();
#if TSUME_USE_BITBOARD_INVERSE
        auto out = unmove_impl<true>(p,mover);
#if TSUME_VERIFY_MOVES
        const auto reference = unmove_impl<false>(p,mover);
        bool matches = out.size() == reference.size();
        for (size_t index = 0; matches && index < out.size(); ++index) {
            const auto& a = out[index];
            const auto& b = reference[index];
            matches = a.first.order == b.first.order && a.first.b.sq == b.first.b.sq
                && a.first.b.hand == b.first.b.hand && a.first.b.turn == b.first.b.turn
                && a.second.from == b.second.from && a.second.to == b.second.to
                && a.second.drop == b.second.drop && a.second.promotion == b.second.promotion;
            for (int color = 0; matches && color < 2; ++color) {
                const auto& actual = a.first.b.order[color];
                const auto& expected = b.first.b.order[color];
                matches = actual.n == expected.n;
                for (int i = 0; matches && i < actual.n; ++i) matches = actual.v[i] == expected.v[i];
            }
        }
        if (!matches) {
            std::fprintf(stderr, "Bitboard/reference inverse result or ordering mismatch\n");
            std::abort();
        }
#endif
        return out;
#else
        return unmove_impl<false>(p,mover);
#endif
    }

    template<bool use_bitboards>
    std::vector<std::pair<Pos,Move>> unmove_impl(const Pos& p,int mover) {
        std::vector<std::pair<Pos,Move>> out;int enemy=1-mover;
        std::vector<std::pair<int,bool>> caps{{0,false}};
        for(int t=P;t<K;++t){caps.push_back({t,false});if(promoted[t])caps.push_back({t,true});}
        Board occ=p.board(mover);
        for(int to:p.order) {
            int v=p.b.sq[to];if(color_of(v)!=mover)continue;int pt=std::abs(v);
            if(pt!=K&&pt<9){Pos q=p;q.erase(to);if(mover==0)q.b.set_hand_count(0, pt, q.b.hand[0][pt] + 1);if(q.valid())out.push_back({q,{-1,to,pt,false}});}
            std::vector<std::pair<int,bool>> types{{pt,false}};if(pt>=9)types.push_back({base(pt),true});
            for (auto type : types) {
                Bitboard81 origins;
                if constexpr (use_bitboards) {
                    origins = occ.attack_mask(type.first,to,enemy);
                    origins.intersect(p.b.empty_squares());
                } else {
                    for (int from = 0; from < 81; ++from)
                        if (!p.b.sq[from] && occ.attacks(type.first,to,from,enemy)) origins.set(from,true);
                }
                for (int from = origins.pop_first(); from >= 0; from = origins.pop_first()) {
                for(auto cap:caps) {
                    Pos q=p;q.erase(to);q.put(from,sign(mover)*type.first);
                    if(cap.first) {
                        if(mover==0){if(q.b.hand[0][cap.first]<=0)continue;q.b.set_hand_count(0, cap.first, q.b.hand[0][cap.first] - 1);}
                        q.put(to,sign(enemy)*(cap.second?promoted[cap.first]:cap.first));
                    }
                    if(q.valid())out.push_back({q,{from,to,0,type.second}});
                }
                }
            }
        }
        return out;
    }
    bool forward(const Pos& q,const Move& m,const Pos& p,int mover) {
        Board b=q.board(mover);if(!b.legal(m))return false;b.push(m);
        return b.sq==p.b.sq&&b.hand[0]==p.b.hand[0];
    }
    bool node(const Pos& q,int mover,int remaining) {
        if(!q.dead_ok())return false;
        if(mover==0){if(q.board(1).check())return false;auto b=q.board(0);
            if(remaining>=3&&mate(b,remaining-2))return false;return solve(b,remaining).size()==1;}
        auto b=q.board(1);return b.check()&&defenders(b,remaining)&&!defenders(b,remaining-2);
    }
    int pick(std::mt19937_64& rng,int n){return std::uniform_int_distribution<int>(0,n-1)(rng);}
    bool random_pos(std::mt19937_64& rng,Pos& result) {
        const int types[]={G,S,12,B,R,13,14,N,L,P,9};const int whites[]={P,S,G,L,N};
        for(int attempt=0;attempt<2000;++attempt) {
            tick();int k=pick(rng,27);Pos p;p.put(k,-K);int n=2+pick(rng,3);
            std::vector<int> near;
            for(int dr:{-1,0,1,2})for(int df:{-1,0,1}){
                int r=k/9+dr,f=k%9+df;if(r>=0&&r<9&&f>=0&&f<9&&(dr||df))near.push_back(r*9+f);}
            for(int i=0;i<n;++i){int extra=pick(rng,81),j=pick(rng,int(near.size())+1),s=j==int(near.size())?extra:near[j];
                if(!p.b.sq[s])p.put(s,types[pick(rng,11)]);}
            int counts[]={0,0,1,2};n=counts[pick(rng,4)];
            for(int i=0;i<n;++i){int s=near[pick(rng,int(near.size()))];if(!p.b.sq[s])p.put(s,-whites[pick(rng,5)]);}
            if(p.valid()&&p.dead_ok()&&p.board(1).checkmate()){result=p;return true;}
        }
        return false;
    }
    bool search(const Pos& p,int mover,int r,int n,std::mt19937_64& rng,int& budget,Pos& result) {
        auto cands=unmove(p,mover);std::shuffle(cands.begin(),cands.end(),rng);
        for(auto& v:cands){tick();if(budget<=0)return false;if(!forward(v.first,v.second,p,mover))continue;
            --budget;if(!node(v.first,mover,r+1))continue;
            if(r+1==n){result=v.first;return true;}
            if(search(v.first,1-mover,r+1,n,rng,budget,result))return true;}
        return false;
    }
    std::string generate(int n,unsigned long long seed,int budget,double seconds) {
        if(n<1||n%2==0||budget<1||!std::isfinite(seconds)||seconds<0)throw std::invalid_argument("Invalid generation arguments");
        std::mt19937_64 rng(seed);timed=true;
        deadline=std::chrono::steady_clock::now()+std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(seconds));
        try {
            while(true){tick();Pos p,q;if(!random_pos(rng,p))continue;
                if(ca.size()+cd.size()>400000)clear();int remaining=budget;
                if(!search(p,0,0,n,rng,remaining,q))continue;
                std::vector<Move> moves;Board b=q.board(0);
                if(verify(b,n,moves)){timed=false;std::string out=b.sfen()+"\n";for(auto m:moves)out+=m.usi()+" ";return out;}}
        }catch(const Timeout&){timed=false;return "";}catch(...){timed=false;throw;}
    }
};
std::string move_text(const std::vector<Move>& moves){std::string out;for(auto m:moves){if(!out.empty())out+=' ';out+=m.usi();}return out;}
std::string run_inner(Solver& s,const std::string& op,const std::string& text,int n,int color,unsigned long long seed,int budget,double seconds) {
    if(op=="clear"){s.clear();return "";}
    if(op=="proof_report")return s.dp_proof_report();
    if(op=="proof_export")return s.dp_proof_export();
    if(op=="feedback_export")return s.dp_export_feedback();
    if(op=="generate")return s.generate(n,seed,budget,seconds);
    if(op=="random"){std::mt19937_64 rng(seed);Pos p;return s.random_pos(rng,p)?p.board(1).sfen():"";}
    if(op=="forward") {
        std::istringstream in(text);std::string q,p,m;
        if(!std::getline(in,q)||!std::getline(in,p)||!std::getline(in,m))throw std::invalid_argument("Invalid forward arguments");
        return s.forward(Pos::from(Board::parse(q)),parse_move(m),Pos::from(Board::parse(p)),color)?"1":"0";
    }
    if(op=="oracle_min"){s.oracle_min=n<3?3:n;return "";}
    if(op=="evfilter"){Board::evfilter_on()=n!=0;s.clear();return "";}
    if(op=="fastchecks"){Board::fastchecks_on()=n!=0;s.clear();return "";}
    if(op=="direct"){Board::direct_on()=n!=0;s.clear();return "";}
    if(op=="kingtab"){Board::kingtab_on()=n!=0;s.clear();return "";}
    if(op=="cap"){s.cache_cap=n>0?size_t(n):size_t(TSUME_CAP);return "";}
    if(op=="batch"){s.batch_on=n!=0;s.clear();return "";}
    if(op=="futile_floor"){s.futile_floor=n<0?0:n;return "";}
    if(op=="final_alt"){s.final_alt=n!=0;return "";}
    if(op=="oracle_stats")return std::to_string(s.o_calls)+" "+std::to_string(s.o_pruned);
    Board b=Board::parse(text);
    if(b.king(1)<0)throw std::invalid_argument("Defender king is required");
    if(op=="checks")return move_text(s.checks(b));
    if(op=="evasions")return move_text(s.evasions(b));
    if(op=="moves")return move_text(b.board_moves(color));
    if(op=="dfpn")return s.dfpn_quick(b);
    if(op=="dfpn_trace")return s.dfpn_with_nonmate_trace(b);
    if(op=="nonmate_trace")return s.nm_export();
    if(op=="dfpn_excluding"){
        std::istringstream in(text);std::string line,m;std::getline(in,line);
        std::vector<Move> excluded;while(in>>m)excluded.push_back(parse_move(m));
        return s.dfpn_excluding(b,excluded);
    }
    if(op=="dfpn_proof")return s.dfpn_record(b,n>0?n:50000);
    if(op=="repair_defense"){
        auto sep=text.find('\n');if(sep==std::string::npos)throw std::invalid_argument("Missing interposition move");
        return s.dfpn_repair_defense(b,parse_move(text.substr(sep+1)),n,budget>0?budget:50000);
    }
    if(op=="prime")return s.dfpn_prime(b);
    if(op=="hints_off"){s.hints_on=false;s.chint.clear();s.dhint.clear();return "";}
    if(op=="can_mate")return s.mate(b,n)?"1":"0";
    if(op=="defenders")return s.defenders(b,n)?"1":"0";
    if(op=="exact")return s.exact(b,n)?"1":"0";
    if(op=="solve")return move_text(s.solve(b,n));
    if(op=="winmove") {   // 手数nで詰むと確認した直後に呼ぶ。確認に使った初手を、全初手を調べ直さずに取り出す。無ければ "-"
        if(!s.mate(b,n))return "-";
#ifdef WINMOVE_TEST
        s.chint.clear();   // 試験用：手がかりが消えた状態を再現する
#endif
        auto it=s.chint.find(s.key(b,0));
        if(it!=s.chint.end()){Board q=b;q.push(it->second);if(s.defenders(q,n-1))return move_text(std::vector<Move>{it->second});}
        // 手がかりが記憶の整理で消えていた場合：「この初手の後は詰む」と記憶に残っている初手を探す（探索はしない）
        for(auto m:s.checks(b)){Board q=b;q.push(m);bool r=false;
            if(s.dom_get(1,q,n-1,r)&&r)return move_text(std::vector<Move>{m});
            auto ci=s.cd.find(s.key(q,n-1));if(ci!=s.cd.end()&&ci->second)return move_text(std::vector<Move>{m});}
        return "-";
    }
    if(op=="legal"||op=="pseudo") {
        auto sep=text.find('\n');if(sep==std::string::npos)throw std::invalid_argument("Missing USI move");
        auto m=parse_move(text.substr(sep+1));return (op=="legal"?b.legal(m):b.pseudo(m))?"1":"0";
    }
    if(op=="futile") {
        auto sep=text.find('\n');if(sep==std::string::npos||n<0||n>=81)throw std::invalid_argument("Invalid futile arguments");
        return s.futile(b,parse_move(text.substr(sep+1)),n,budget)?"1":"0";
    }
    if(op=="hintline") {   // 手順（USIの手を空白で区切る）の攻め方の手を、精密な探索が先に試す手として登録する
        auto sep=text.find('\n');if(sep==std::string::npos)throw std::invalid_argument("Invalid hintline arguments");
        std::istringstream is(text.substr(sep+1));std::string u;Board c=b;int cnt=0;
        while(is>>u){Move m=parse_move(u);if(!c.pseudo(m))break;if(c.turn==0){s.chint[s.key(c,0)]=m;++cnt;}c.push(m);}
        if(cnt>0)s.hints_on=true;
        return std::to_string(cnt);
    }
    if(op=="line"||op=="verify") {std::vector<Move> moves;
        bool ok=op=="line"?s.line(b,n,moves):s.verify(b,n,moves);return ok?move_text(moves):"-";}
    Pos p=Pos::from(b);
    if(op=="search") {std::mt19937_64 rng(seed);Pos q;int remaining=budget;
        return s.search(p,color,0,n,rng,remaining,q)?q.board(0).sfen()+"\n"+std::to_string(remaining):"-\n"+std::to_string(remaining);}
    if(op=="dead")return p.dead_ok()?"1":"0";
    if(op=="node")return s.node(p,color,n)?"1":"0";
    if(op=="unmove"){std::string out;for(auto& v:s.unmove(p,color))out+=v.first.board(color).sfen()+"\t"+v.second.usi()+"\n";return out;}
    throw std::invalid_argument("Unknown operation");
}
std::string run(Solver& s,const std::string& op,const std::string& text,int n,int color,unsigned long long seed,int budget,double seconds) {
    bool use=seconds>0&&std::isfinite(seconds)&&op!="generate"&&op!="search";
    if(!use)return run_inner(s,op,text,n,color,seed,budget,seconds);
    s.timed=true;
    s.deadline=std::chrono::steady_clock::now()+std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(seconds));
    try{auto r=run_inner(s,op,text,n,color,seed,budget,seconds);s.timed=false;return r;}
    catch(const Timeout&){s.timed=false;throw std::runtime_error("timeout");}
    catch(...){s.timed=false;throw;}
}
}
void TSUME_CALL tsume_cancel(int on){g_cancel.store(on!=0);}
void TSUME_CALL tsume_cancel_context(void* p,int on){if(p)static_cast<Solver*>(p)->context_cancel.store(on!=0,std::memory_order_relaxed);}
void TSUME_CALL tsume_set_search_progress(void* p,void (TSUME_CALL *callback)(unsigned long long,double,int)) {
    if(p)static_cast<Solver*>(p)->search_callback=callback;
}
void TSUME_CALL tsume_set_progress(void* p,void (TSUME_CALL *callback)(unsigned long long,double,int)) {
    if(p)static_cast<Solver*>(p)->dp_progress_callback=callback;
}
void TSUME_CALL tsume_set_oracle(void* p,int (TSUME_CALL *fn)(const char*)){if(p)static_cast<Solver*>(p)->oracle=fn;}
void* TSUME_CALL tsume_create(){try{return new Solver;}catch(...){return nullptr;}}
void TSUME_CALL tsume_destroy(void* p){delete static_cast<Solver*>(p);}
const char* TSUME_CALL tsume_error(void* p){return p?static_cast<Solver*>(p)->error.c_str():"Null context";}
int TSUME_CALL tsume_copy_result(void* p,char* output,size_t capacity) {
    if(!p)return -1;const auto& r=static_cast<Solver*>(p)->last_output;
    if(output&&capacity>=r.size()+1)std::memcpy(output,r.c_str(),r.size()+1);
    return int(r.size()+1);
}
int TSUME_CALL tsume_run(void* p,const char* op,const char* sfen,int n,int color,unsigned long long seed,int budget,double seconds,char* output,size_t capacity) {
    if(!p)return -1;Solver& s=*static_cast<Solver*>(p);s.error.clear();
    Solver::SearchProgressScope search_progress(s);
    try {
        if(!op||!sfen||color<0||color>1)throw std::invalid_argument("Invalid arguments");
        s.last_output=run(s,op,sfen,n,color,seed,budget,seconds);
        const auto& result=s.last_output;
        if(result.size()>2147483646u)throw std::length_error("Output too large");
        size_t required=result.size()+1;
        if(output&&capacity>=required)std::memcpy(output,result.c_str(),required);
        return int(required);
    }catch(const std::exception& e){s.error=e.what();return -1;}catch(...){s.error="Internal native error";return -1;}
}
