#pragma once

// Each family is a single line. Rook/bishop combine two line lookups.
// This bounds the relevant occupancy to seven bits per line on a 9x9 board.
enum class SliderFamily { Rank, File, DiagonalDown, DiagonalUp };

struct SliderLayout {
    Bitboard81 mask;
    std::vector<int> relevant;
    int from;
    SliderFamily family;
    int rotation = 0;

    static bool inside(int row, int file) {
        return row >= 0 && row < 9 && file >= 0 && file < 9;
    }

    static uint64_t rotate(uint64_t bits, int amount) {
        if (amount == 0) return bits;
        return (bits << amount) | (bits >> (64 - amount));
    }

    std::pair<int, int> direction() const {
        switch (family) {
        case SliderFamily::Rank: return {0, 1};
        case SliderFamily::File: return {1, 0};
        case SliderFamily::DiagonalDown: return {1, 1};
        case SliderFamily::DiagonalUp: return {1, -1};
        }
        throw std::logic_error("Invalid slider family");
    }

    SliderLayout(SliderFamily selected_family, int square)
        : from(square), family(selected_family) {
        const auto step = direction();
        for (int sign : {-1, 1}) {
            const int dr = sign * step.first;
            const int df = sign * step.second;
            int row = from / 9 + dr;
            int file = from % 9 + df;
            while (inside(row, file)) {
                // The final edge square cannot affect attacks beyond itself.
                if (inside(row + dr, file + df))
                    mask.set(row * 9 + file, true);
                row += dr;
                file += df;
            }
        }
        for (int square_index = 0; square_index < 81; ++square_index)
            if (mask.contains(square_index)) relevant.push_back(square_index);
        if (relevant.size() > 7)
            throw std::logic_error("Slider occupancy exceeds seven bits");
        while (rotation < 64 && (mask.low & rotate(mask.high, rotation)) != 0)
            ++rotation;
        if (rotation == 64)
            throw std::logic_error("Cannot fold slider occupancy without overlap");
    }

    uint64_t fold(const Bitboard81& occupied) const {
        return (occupied.low & mask.low) | rotate(occupied.high & mask.high, rotation);
    }

    Bitboard81 subset(unsigned number) const {
        Bitboard81 occupied;
        for (size_t bit = 0; bit < relevant.size(); ++bit)
            if (number & (1u << bit)) occupied.set(relevant[bit], true);
        return occupied;
    }

    Bitboard81 trace(const Bitboard81& occupied) const {
        Bitboard81 attacks;
        const auto step = direction();
        for (int sign : {-1, 1}) {
            const int dr = sign * step.first;
            const int df = sign * step.second;
            int row = from / 9 + dr;
            int file = from % 9 + df;
            while (inside(row, file)) {
                const int target = row * 9 + file;
                attacks.set(target, true);
                if (occupied.contains(target)) break;
                row += dr;
                file += df;
            }
        }
        return attacks;
    }
};

struct SliderMagicSpec {
    uint64_t multiplier;
    unsigned shift;
};

#ifndef TSUME_GENERATE_MAGICS
#include "slider_magic_constants.h"

struct SliderMagicEntry {
    SliderLayout layout;
    SliderMagicSpec spec;
    std::vector<Bitboard81> attacks;

    size_t index(const Bitboard81& occupied) const {
        if (layout.relevant.empty()) return 0;
        return size_t((layout.fold(occupied) * spec.multiplier) >> spec.shift);
    }

    SliderMagicEntry(SliderFamily family, int square, SliderMagicSpec selected_spec)
        : layout(family, square), spec(selected_spec) {
        const unsigned bits = unsigned(layout.relevant.size());
        if (bits != 0 && (spec.multiplier == 0 || spec.shift > 63
                         || 64 - spec.shift > bits + 1))
            throw std::logic_error("Invalid slider magic specification");
        const size_t capacity = bits == 0 ? 1 : size_t(1) << (64 - spec.shift);
        attacks.resize(capacity);
        std::vector<bool> used(capacity, false);
        for (unsigned subset_index = 0; subset_index < (1u << bits); ++subset_index) {
            const auto occupied = layout.subset(subset_index);
            const size_t slot = index(occupied);
            if (slot >= attacks.size() || used[slot])
                throw std::logic_error("Slider magic occupancy collision");
            used[slot] = true;
            attacks[slot] = layout.trace(occupied);
        }
    }

    const Bitboard81& lookup(const Bitboard81& occupied) const {
        return attacks[index(occupied)];
    }
};

struct SliderMagicTables {
    std::array<std::vector<SliderMagicEntry>, 4> lines;
    std::array<std::array<Bitboard81, 81>, 2> lance_rays{};
    std::array<std::array<Bitboard81, 81>, 2> promoted_steps{};

    SliderMagicTables() {
        for (int family = 0; family < 4; ++family) {
            lines[family].reserve(81);
            for (int square = 0; square < 81; ++square)
                lines[family].emplace_back(SliderFamily(family), square,
                                          slider_magic_specs[family][square]);
        }
        for (int color = 0; color < 2; ++color)
            for (int square = 0; square < 81; ++square) {
                const int forward = color == 0 ? -1 : 1;
                for (int row = square / 9 + forward; row >= 0 && row < 9; row += forward)
                    lance_rays[color][square].set(row * 9 + square % 9, true);
            }
        const int offsets[2][4][2] = {
            {{-1, 0}, {1, 0}, {0, -1}, {0, 1}},
            {{-1, -1}, {-1, 1}, {1, -1}, {1, 1}},
        };
        for (int kind = 0; kind < 2; ++kind)
            for (int square = 0; square < 81; ++square)
                for (const auto& offset : offsets[kind]) {
                    const int row = square / 9 + offset[0];
                    const int file = square % 9 + offset[1];
                    if (SliderLayout::inside(row, file))
                        promoted_steps[kind][square].set(row * 9 + file, true);
                }
    }

    static const SliderMagicTables& get() {
        static const SliderMagicTables tables;
        return tables;
    }

    Bitboard81 lookup(int piece, int square, int color, const Bitboard81& occupied) const {
        if (piece == L) {
            const auto& file = lines[int(SliderFamily::File)][square].lookup(occupied);
            const auto& ray = lance_rays[color][square];
            return {file.low & ray.low, file.high & ray.high};
        }
        const int first = piece == B || piece == 13 ? 2 : 0;
        const auto& a = lines[first][square].lookup(occupied);
        const auto& b = lines[first + 1][square].lookup(occupied);
        Bitboard81 result{a.low | b.low, a.high | b.high};
        if (piece == 13 || piece == 14) {
            const auto& steps = promoted_steps[piece - 13][square];
            result.low |= steps.low;
            result.high |= steps.high;
        }
        return result;
    }

    // Specialized queen rays avoid two generic piece-dispatch calls when
    // identifying the nearest occupied square in every direction.
    Bitboard81 queen_rays(int square, const Bitboard81& occupied) const {
        const auto& rank = lines[0][square].lookup(occupied);
        const auto& file = lines[1][square].lookup(occupied);
        const auto& down = lines[2][square].lookup(occupied);
        const auto& up = lines[3][square].lookup(occupied);
        return {rank.low | file.low | down.low | up.low,
                rank.high | file.high | down.high | up.high};
    }

    size_t payload_bytes() const {
        size_t size = sizeof(lance_rays) + sizeof(promoted_steps);
        for (const auto& family : lines)
            for (const auto& entry : family)
                size += entry.attacks.size() * sizeof(Bitboard81);
        return size;
    }
};
#endif
