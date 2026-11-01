#include "tsume.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#ifndef ORD
#define ORD 1
#endif
#ifndef AORD
#define AORD 0
#endif
#ifndef TSUME_CAP
#define TSUME_CAP 8000000
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
struct Board {
    std::array<int,81> sq{};
    std::array<std::array<int,9>,2> hand{};
    std::array<SmallOrder,2> order;
    int turn=0;
    int king(int c) const { for(int s=0;s<81;++s) if(sq[s]==sign(c)*K)return s;return -1; }
    void add(int c,int p,int n=1) {
        if(p==K) return;
        if(!hand[c][p]) order[c].push_back(p);
        hand[c][p]+=n;
    }
    void remove(int c,int p) {
        if(--hand[c][p]==0) {
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
            b.sq[r*9+f++]=sign(c)*pt;prom=false;
        }
        (void)s;
        if(r!=8||f!=9||prom)throw std::invalid_argument("Invalid SFEN board");
        b.turn=t=="w";int count=0;
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
    bool attacks(int pt,int from,int to,int c) const {
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
    bool attacked(int c,int target,bool no_king=false) const {
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
        if(m.from<0) {remove(turn,m.drop);sq[m.to]=sign(turn)*m.drop;}
        else {
            if(sq[m.to])add(turn,base(std::abs(sq[m.to])));
            int pt=std::abs(sq[m.from]);sq[m.from]=0;
            sq[m.to]=sign(turn)*(m.promotion?promoted[pt]:pt);
        }
        turn^=1;
    }
    bool pseudo(const Move& m) const {
        if(m.to<0||m.to>=81||(sq[m.to]&&color_of(sq[m.to])==turn))return false;
        if(m.from>=0) {
            if(m.from>=81||!sq[m.from]||color_of(sq[m.from])!=turn)return false;
            int pt=std::abs(sq[m.from]);
            if(m.promotion&&(!promoted[pt]||(!zone(m.from,turn)&&!zone(m.to,turn))))return false;
            return (m.promotion||mobile(pt,m.to,turn))&&attacks(pt,m.from,m.to,turn);
        }
        if(m.drop<P||m.drop>=K||m.promotion||!hand[turn][m.drop]||!mobile(m.drop,m.to,turn))return false;
        if(m.drop==P)for(int r=0;r<9;++r)if(sq[r*9+m.to%9]==sign(turn)*P)return false;
        return true;
    }
    // Fast legal(): temporarily edits sq and restores it (no Board copy). Same result as before.
    struct Undo {Board* b;int from,to,fv,tv;
        ~Undo(){if(from>=0)b->sq[from]=fv;b->sq[to]=tv;}};
    bool legal(const Move& m) const {
        if(!pseudo(m))return false;
        return legal_body(m);
    }
    // For moves produced by board_moves(turn): only the mobility test of pseudo() is still needed.
    bool legal_bm(const Move& m) const {
        if(!m.promotion&&!mobile(std::abs(sq[m.from]),m.to,turn))return false;
        return legal_body(m);
    }
    bool legal_body(const Move& m) const {
        Board* self=const_cast<Board*>(this);
        int mover=turn,opp=turn^1;
        Undo u{self,m.from,m.to,m.from>=0?sq[m.from]:0,sq[m.to]};
        if(m.from<0)self->sq[m.to]=sign(mover)*m.drop;
        else {int pt=std::abs(sq[m.from]);self->sq[m.to]=sign(mover)*(m.promotion?promoted[pt]:pt);self->sq[m.from]=0;}
        if(attacked(opp,king(mover)))return false;
        // Match python-shogi's pawn-drop-mate test, including its documented limitation.
        if(m.drop!=P)return true;
        int k=king(opp);
        if(k<0||!attacks(P,m.to,k,mover))return true;
        for(int s=0;s<81;++s)if(attacks(K,k,s,opp)&&(!sq[s]||color_of(sq[s])!=opp))
            if(!attacked(mover,s))return true;
        return attacked(opp,m.to,true);
    }
    // True if the move gives check to the opponent king (no Board copy).
    bool gives_check(const Move& m) const {
        Board* self=const_cast<Board*>(this);
        int mover=turn;
        Undo u{self,m.from,m.to,m.from>=0?sq[m.from]:0,sq[m.to]};
        if(m.from<0)self->sq[m.to]=sign(mover)*m.drop;
        else {int pt=std::abs(sq[m.from]);self->sq[m.to]=sign(mover)*(m.promotion?promoted[pt]:pt);self->sq[m.from]=0;}
        return attacked(mover,king(mover^1));
    }
    std::vector<Move> board_moves(int c) const {
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
        for(int s=0;s<81;++s)if(!sq[s])for(int p=P;p<K;++p)
            if(hand[turn][p]&&legal({-1,s,p,false}))return false;
        return true;
    }
};

struct Pos {
    Board b;
    // Keep dictionary insertion order for inverse move enumeration.
    std::vector<int> order;
    static Pos from(const Board& b) {
        Pos p;p.b=b;for(int s=0;s<81;++s)if(b.sq[s])p.order.push_back(s);return p;
    }
    std::array<int,9> remainder() const {
        std::array<int,9> used=b.hand[0],rest{};
        for(int v:b.sq)if(v&&std::abs(v)!=K)++used[base(std::abs(v))];
        for(int p=P;p<K;++p)rest[p]=totals[p]-used[p];return rest;
    }
    bool valid() const {auto r=remainder();for(int p=P;p<K;++p)if(r[p]<0)return false;return true;}
    Board board(int turn) const {
        Board q=b;q.turn=turn;q.hand[1]=remainder();
        for(int c=0;c<2;++c){q.order[c].clear();for(int p:{R,B,G,S,N,L,P})if(q.hand[c][p])q.order[c].push_back(p);}
        return q;
    }
    void erase(int s){b.sq[s]=0;order.erase(std::remove(order.begin(),order.end(),s),order.end());}
    void put(int s,int v){if(!b.sq[s])order.push_back(s);b.sq[s]=v;}
    bool dead_ok() const {for(int s=0;s<81;++s)if(b.sq[s]&&!mobile(std::abs(b.sq[s]),s,color_of(b.sq[s])))return false;return true;}
};

struct Timeout {};
struct Solver {
    std::unordered_map<uint64_t,bool> ca,cd,cf;
    // Optional oracle: returns 1 (mate under normal rules), -1 (no mate), 0 (unknown). Used only to prune attacker nodes.
    int (*oracle)(const char*)=nullptr;
    std::unordered_map<uint64_t,int> ost;
    long long o_calls=0,o_pruned=0;
    int oracle_min=5;
    bool final_alt=false; // allow several last moves (any square) when true
    std::string error;
    std::string last_output;
    bool timed=false;
    std::chrono::steady_clock::time_point deadline;
    void tick(){if(timed&&std::chrono::steady_clock::now()>=deadline)throw Timeout{};}
    void clear(){ca.clear();cd.clear();cf.clear();dom[0].clear();dom[1].clear();dom_count=0;chint.clear();dhint.clear();}
    std::unordered_map<uint64_t,Move> chint,dhint;   // move-ordering hints (do not affect results)
    bool hints_on=false;
    size_t cache_cap=TSUME_CAP;
    void trim(){if(ca.size()+cd.size()+cf.size()+dom_count>cache_cap){ca.clear();cd.clear();cf.clear();ost.clear();dom[0].clear();dom[1].clear();dom_count=0;chint.clear();dhint.clear();}}
    static uint64_t fnv(const std::string& k,uint64_t h=1469598103934665603ULL){for(unsigned char c:k){h^=c;h*=1099511628211ULL;}h^=h>>29;h*=0xbf58476d1ce4e5b9ULL;h^=h>>32;return h;}
    uint64_t key(const Board& b,int n) {
        uint64_t h=1469598103934665603ULL;
        auto put=[&](unsigned c){h^=(c&255u);h*=1099511628211ULL;};
        for(int v:b.sq)put(unsigned(v+16));
        put(unsigned(b.turn));
        for(auto& hh:b.hand)for(int p=P;p<K;++p){put(unsigned(hh[p]&255));put(unsigned((hh[p]>>8)&255));}
        for(int i=0;i<4;++i)put((unsigned(n)>>(i*8))&255u);
        h^=h>>29;h*=0xbf58476d1ce4e5b9ULL;h^=h>>32;return h;
    }
    std::vector<Move> checks(const Board& b) {
        tick();std::vector<Move> out;int k=b.king(1);
        for(int p:b.order[0])if(b.hand[0][p]>0)for(int s=0;s<81;++s)
            if(!b.sq[s]&&b.attacks(p,k,s,1)) {Move m{-1,s,p,false};if(b.legal(m))out.push_back(m);}
        for(auto m:b.board_moves(0))if(b.pseudo(m)){if(b.gives_check(m))out.push_back(m);}
        return out;
    }
    std::unordered_set<uint64_t> inprog;
    int fdepth=0,maxDepth=6;
    // Futile interposition: after the slider captures the dropped piece, remove that piece from the attacker's hand;
    // if mate is still reached within n plies, the drop is futile (n=0: only when no evasion remains).
    bool futile(const Board& b,const Move& d,int a,int n=0) {
        auto k=key(b,n)*0x9E3779B97F4A7C15ULL+uint64_t(d.to+1)*131+uint64_t(d.drop)*17+(d.from<0?7:uint64_t(d.from)*257)+(d.promotion?3:0);k^=k>>31;auto it=cf.find(k);if(it!=cf.end())return it->second;
        if(inprog.count(k))return false;
        bool wide=n>=1&&fdepth<maxDepth;
        if(wide){inprog.insert(k);++fdepth;}
        bool res=false;
        try {
            Board q=b;q.push(d);
            for(bool prom:{false,true}) {Move m{a,d.to,0,prom};if(!q.pseudo(m))continue;
                Board r=q;r.push(m);if(!r.check())continue;
                if(!wide){if(!has_evasion(r,0)){res=true;break;}}
                else {r.remove(0,d.drop);if(defenders(r,n)){res=true;break;}}
            }
        } catch(...) {if(wide){inprog.erase(k);--fdepth;}throw;}
        if(wide){inprog.erase(k);--fdepth;}
        cf[k]=res;return res;
    }
    std::vector<Move> evasions(const Board& b,int bud=0) {
        tick();std::vector<Move> out;
        if(b.turn==1){for(auto m:b.board_moves(1))if(b.legal_bm(m))out.push_back(m);}
        else for(auto m:b.board_moves(1))if(b.legal(m))out.push_back(m);
        int k=b.king(1),a=-1,count=0;
        for(int s=0;s<81;++s)if(b.sq[s]>0&&b.attacks(b.sq[s],s,k,0)){a=s;++count;}
        if(count!=1)return out;
        int pt=std::abs(b.sq[a]),dr=a/9-k/9,df=a%9-k%9,dist=std::max(std::abs(dr),std::abs(df));
        if(!(pt==L||pt==B||pt==R||pt==13||pt==14)||dist<=1||!(dr==0||df==0||std::abs(dr)==std::abs(df)))return out;
        int sr=(dr>0)-(dr<0),sf=(df>0)-(df<0);
        for(int i=1;i<dist;++i) {
            int s=(k/9+sr*i)*9+k%9+sf*i;
            for(int p:b.order[1])if(b.hand[1][p]>0) {
                Move m{-1,s,p,false};if(b.legal(m)&&!futile(b,m,a,bud))out.push_back(m);
            }
        }
        return out;
    }
    // Like evasions() but returns interposition drops without testing futility (caller tests lazily).
    void evasions_split(const Board& b,std::vector<Move>& normal,std::vector<Move>& drops,int& att) {
        tick();att=-1;
        if(b.turn==1){for(auto m:b.board_moves(1))if(b.legal_bm(m))normal.push_back(m);}
        else for(auto m:b.board_moves(1))if(b.legal(m))normal.push_back(m);
        int k=b.king(1),a=-1,count=0;
        for(int s=0;s<81;++s)if(b.sq[s]>0&&b.attacks(b.sq[s],s,k,0)){a=s;++count;}
        if(count!=1)return;
        int pt=std::abs(b.sq[a]),dr=a/9-k/9,df=a%9-k%9,dist=std::max(std::abs(dr),std::abs(df));
        if(!(pt==L||pt==B||pt==R||pt==13||pt==14)||dist<=1||!(dr==0||df==0||std::abs(dr)==std::abs(df)))return;
        int sr=(dr>0)-(dr<0),sf=(df>0)-(df<0);
        for(int i=1;i<dist;++i) {
            int s=(k/9+sr*i)*9+k%9+sf*i;
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
    std::unordered_map<uint64_t,std::vector<DomEntry>> dom[2];
    size_t dom_count=0;
    bool dom_on=true;
    static uint64_t dom_key(const Board& b,int n) {
        uint64_t h=1469598103934665603ULL;
        auto put=[&](unsigned c){h^=(c&255u);h*=1099511628211ULL;};
        for(int v:b.sq)put(unsigned(v+16));
        put(unsigned(b.turn));
        for(int i=0;i<4;++i)put((unsigned(n)>>(i*8))&255u);
        h^=h>>29;h*=0xbf58476d1ce4e5b9ULL;h^=h>>32;return h;
    }
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
        if(v.size()>=16)v.erase(v.begin());
        v.push_back(e);++dom_count;
    }
    bool mate(const Board& b,int n) {
        bool r;if(dom_get(0,b,n,r))return r;
        r=mate_impl(b,n);dom_put(0,b,n,r);return r;
    }
    bool defenders(const Board& b,int n) {
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
        uint64_t hk=0;bool have_h=false;Move hm;
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
            size_t nb=0;if(q.turn==1){for(auto e:q.board_moves(1))if(q.legal_bm(e))++nb;}else{for(auto e:q.board_moves(1))if(q.legal(e))++nb;}
            if(nb==0){auto ev=evasions(q,n-1);
                if(ev.empty()){if(hints_on&&n>=3)chint[key(b,0)]=m;return ca[k]=true;}scored.push_back({ev.size(),m});}
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
        uint64_t hk=0;
        if(hints_on&&n>=2) {
            hk=key(b,0);auto hi=dhint.find(hk);
            if(hi!=dhint.end()) {
                Move hm=hi->second;Board q=b;q.push(hm);
                if(!mate(q,n-1)) {
                    if(hm.from>=0)return cd[k]=false;
                    std::vector<Move> nm,dr;int at;evasions_split(b,nm,dr,at);
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
        tick();std::vector<std::pair<Pos,Move>> out;int enemy=1-mover;
        std::vector<std::pair<int,bool>> caps{{0,false}};
        for(int t=P;t<K;++t){caps.push_back({t,false});if(promoted[t])caps.push_back({t,true});}
        Board occ=p.board(mover);
        for(int to:p.order) {
            int v=p.b.sq[to];if(color_of(v)!=mover)continue;int pt=std::abs(v);
            if(pt!=K&&pt<9){Pos q=p;q.erase(to);if(mover==0)++q.b.hand[0][pt];if(q.valid())out.push_back({q,{-1,to,pt,false}});}
            std::vector<std::pair<int,bool>> types{{pt,false}};if(pt>=9)types.push_back({base(pt),true});
            for(auto type:types)for(int from=0;from<81;++from) {
                if(p.b.sq[from]||!occ.attacks(type.first,to,from,enemy))continue;
                for(auto cap:caps) {
                    Pos q=p;q.erase(to);q.put(from,sign(mover)*type.first);
                    if(cap.first) {
                        if(mover==0){if(q.b.hand[0][cap.first]<=0)continue;--q.b.hand[0][cap.first];}
                        q.put(to,sign(enemy)*(cap.second?promoted[cap.first]:cap.first));
                    }
                    if(q.valid())out.push_back({q,{from,to,0,type.second}});
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
    if(op=="generate")return s.generate(n,seed,budget,seconds);
    if(op=="random"){std::mt19937_64 rng(seed);Pos p;return s.random_pos(rng,p)?p.board(1).sfen():"";}
    if(op=="forward") {
        std::istringstream in(text);std::string q,p,m;
        if(!std::getline(in,q)||!std::getline(in,p)||!std::getline(in,m))throw std::invalid_argument("Invalid forward arguments");
        return s.forward(Pos::from(Board::parse(q)),parse_move(m),Pos::from(Board::parse(p)),color)?"1":"0";
    }
    if(op=="oracle_min"){s.oracle_min=n<3?3:n;return "";}
    if(op=="final_alt"){s.final_alt=n!=0;return "";}
    if(op=="oracle_stats")return std::to_string(s.o_calls)+" "+std::to_string(s.o_pruned);
    Board b=Board::parse(text);
    if(b.king(1)<0)throw std::invalid_argument("Defender king is required");
    if(op=="checks")return move_text(s.checks(b));
    if(op=="evasions")return move_text(s.evasions(b));
    if(op=="moves")return move_text(b.board_moves(color));
    if(op=="can_mate")return s.mate(b,n)?"1":"0";
    if(op=="defenders")return s.defenders(b,n)?"1":"0";
    if(op=="exact")return s.exact(b,n)?"1":"0";
    if(op=="solve")return move_text(s.solve(b,n));
    if(op=="legal"||op=="pseudo") {
        auto sep=text.find('\n');if(sep==std::string::npos)throw std::invalid_argument("Missing USI move");
        auto m=parse_move(text.substr(sep+1));return (op=="legal"?b.legal(m):b.pseudo(m))?"1":"0";
    }
    if(op=="futile") {
        auto sep=text.find('\n');if(sep==std::string::npos||n<0||n>=81)throw std::invalid_argument("Invalid futile arguments");
        return s.futile(b,parse_move(text.substr(sep+1)),n,budget)?"1":"0";
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
