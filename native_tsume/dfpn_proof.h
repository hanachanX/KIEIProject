// Included inside Solver. Diagnostic witnesses never answer strict-engine queries.
struct ProofOmission { Move move; };
struct ProofHandReuse { Move move;std::string source; };
struct ProofNode {
    std::string position;
    std::string adapted_from;
    int prune=0,chain=0,floor=0;
    std::vector<Move> moves;
    std::vector<ProofOmission> omitted;
    std::vector<ProofHandReuse> hand_reused;
};
std::unordered_map<Key128,ProofNode,KH> dp_proofs;
std::unordered_map<Key128,ProofNode,KH> dp_adapted_proofs;
size_t dp_adapted_edges=0;
bool dp_proof_recording=false,dp_proof_truncated=false;
bool dp_last_proof_complete=false;size_t dp_last_proof_pending=0;
size_t dp_proof_cap=50000,dp_proof_edge_cap=200000,dp_proof_edges=0;
std::string dp_proof_root,dp_proof_result="none";
int dp_proof_floor=0;
Key128 dp_proof_root_key{0,0};
void dp_proof_clear() {
    dp_proofs.clear();dp_adapted_proofs.clear();dp_adapted_edges=0;dp_proof_edges=0;dp_proof_truncated=false;dp_last_proof_complete=false;dp_last_proof_pending=0;
    dp_proof_root.clear();dp_proof_result="none";dp_proof_root_key={0,0};
}
void dp_proof_attempt() {
    if(!dp_proof_recording)return;
    dp_proofs.clear();dp_adapted_proofs.clear();dp_adapted_edges=0;dp_proof_edges=0;dp_proof_truncated=false;dp_last_proof_complete=false;dp_last_proof_pending=0;
}
static bool proof_same_move(const Move&a,const Move&b) {
    return a.from==b.from&&a.to==b.to&&a.drop==b.drop&&a.promotion==b.promotion;
}
static bool proof_contains(const std::vector<Move>& ms,const Move&m) {
    for(const auto&x:ms)if(proof_same_move(x,m))return true;
    return false;
}
static bool proof_same_position(const Board&a,const Board&b) {
    if(a.turn!=b.turn)return false;
    for(int i=0;i<81;++i)if(a.sq[i]!=b.sq[i])return false;
    for(int c=0;c<2;++c)for(int p=P;p<K;++p)if(a.hand[c][p]!=b.hand[c][p])return false;
    return true;
}
std::string proof_hand_source(const Board&b) {
    DP value;bool exact;
    if(!dp_look(b,value,exact)||exact||value.pn!=0)return "";
    auto f=dpt.find(dom_key(b,0));if(f==dpt.end())return "";
    uint8_t a[7],d[7];dp_hands(b,a,d);
    for(const auto&e:f->second){if(e.pn!=0)continue;bool matches=true;
        for(int i=0;i<7&&matches;++i)matches=e.a[i]<=a[i]&&e.d[i]>=d[i];
        if(!matches)continue;
        Board source=b;
        for(int i=0;i<7;++i){
            while(source.hand[0][i+1]>0)source.remove(0,i+1);if(e.a[i])source.add(0,i+1,e.a[i]);
            while(source.hand[1][i+1]>0)source.remove(1,i+1);if(e.d[i])source.add(1,i+1,e.d[i]);
        }
        return source.sfen();
    }
    return "";
}
void dp_record_mate(const Board&b,const std::vector<DItem>&items) {
    if(!dp_proof_recording)return;
    const auto k=key(b,0);
    auto old=dp_proofs.find(k);
    // Reserve a node and an edge for the root so a bounded trace can still
    // identify missing child proofs rather than losing the root altogether.
    const bool root=(k==dp_proof_root_key);
    const bool reserve_root=!root&&dp_proofs.find(dp_proof_root_key)==dp_proofs.end();
    const size_t usable=dp_proof_cap-(reserve_root?1:0);
    if(old==dp_proofs.end()&&dp_proofs.size()>=usable){dp_proof_truncated=true;return;}
    ProofNode record;record.position=b.sfen();record.prune=dp_prune;
    record.chain=dp_chain;record.floor=futile_floor;
    if(b.turn==0) {
        // One independent winning attack is enough. Do not invent a child witness
        // when pn=0 came only from a hand-dominance lookup.
        for(const auto&item:items){DP value=dp_child_value(item);
            if(value.pn==0&&!value.path_dependent){record.moves.push_back(item.m);break;}}
        if(record.moves.empty())return;
    } else {
        for(const auto&item:items){record.moves.push_back(item.m);
            for(const auto&m:item.rest)record.moves.push_back(m);}
        std::vector<Move> normal,drops;int attacker;evasions_split(b,normal,drops,attacker);
        // Every omitted raw defense is recorded. The checker will verify that
        // the recorded search policy really explains it, not that it is futile.
        for(const auto&m:normal)if(!proof_contains(record.moves,m))record.omitted.push_back({m});
        for(const auto&m:drops)if(!proof_contains(record.moves,m))record.omitted.push_back({m});
    }
    for(const auto&m:record.moves){Board child=b;child.push(m);auto source=proof_hand_source(child);
        if(!source.empty())record.hand_reused.push_back({m,std::move(source)});}
    const size_t old_edges=old==dp_proofs.end()?0:old->second.moves.size()+old->second.omitted.size();
    const size_t edges=record.moves.size()+record.omitted.size();
    if(dp_proof_edges-old_edges+edges>dp_proof_edge_cap-(reserve_root?1:0)){dp_proof_truncated=true;return;}
    dp_proof_edges=dp_proof_edges-old_edges+edges;
    dp_proofs[k]=std::move(record);
}
struct ProofPair {
    Key128 target,source;
    bool operator==(const ProofPair&other)const{return target==other.target&&source==other.source;}
};
struct ProofPairHash {
    size_t operator()(const ProofPair&pair)const {
        const size_t a=KH{}(pair.target),b=KH{}(pair.source);
        return a^(b+size_t(0x9e3779b9)+(a<<6)+(a>>2));
    }
};
struct ProofCheck {
    size_t visited=0,missing=0,invalid=0,cycles=0,pending=0,hand_reused=0,hand_missing=0;
    size_t hand_resolved=0,adaptation_visits=0,ignored_source_defenses=0,uncovered_defenses=0,checked_pairs=0;
    bool limited=false;
    std::string limit_reason;
    std::unordered_map<ProofPair,int,ProofPairHash> heights;
    // Keep the first completed strategy for each target. Different templates
    // cannot overwrite it and accidentally create cycles in the exported graph.
    std::unordered_map<Key128,int,KH> completed;
    std::unordered_set<Key128,KH> path;
    std::vector<std::string> missing_examples,missing_source_examples;
    std::vector<std::pair<std::string,std::string>> pending_defenses;
};
static bool proof_hand_dominates(const Board&target,const Board&source) {
    if(target.turn!=source.turn)return false;
    for(int i=0;i<81;++i)if(target.sq[i]!=source.sq[i])return false;
    for(int p=P;p<K;++p)
        if(target.hand[0][p]<source.hand[0][p]||target.hand[1][p]>source.hand[1][p])return false;
    return true;
}
static const ProofHandReuse* proof_reuse_for(const ProofNode&node,const Move&m) {
    for(const auto&reuse:node.hand_reused)if(proof_same_move(reuse.move,m))return &reuse;
    return nullptr;
}
bool proof_omission_allowed(const Board&b,const Move&m,const std::vector<Move>&normal,
                            const std::vector<Move>&drops,const ProofNode&node) {
    if(node.prune!=1||!normal.empty()||m.from>=0||!proof_contains(drops,m)||dp_defense_required(b,m))return false;
    const int king=b.king(1);
    const int dist=std::max(std::abs(m.to/9-king/9),std::abs(m.to%9-king%9));
    return dist>=2&&!dp_support_reference(b,m.to,m.from);
}
int dp_check_proof_child(const Board&target,const Board&source,const ProofNode&node,
                         const Move&m,ProofCheck&check,int depth) {
    const auto*reuse=proof_reuse_for(node,m);
    if(reuse)++check.hand_reused;
    // Prefer an exact target record, then the corresponding source record.
    // Only a recorded reuse origin may supply another template; no numerical TT.
    int height;
    if(dp_proofs.find(key(target,0))!=dp_proofs.end())
        height=dp_check_proof_node(target,check,depth);
    else if(dp_proofs.find(key(source,0))!=dp_proofs.end())
        height=dp_check_proof_node(target,check,depth,&source);
    else if(reuse) {
        Board origin=Board::parse(reuse->source);
        height=dp_check_proof_node(target,check,depth,&origin);
    } else height=dp_check_proof_node(target,check,depth,&source);
    if(reuse){if(height<0)++check.hand_missing;else ++check.hand_resolved;}
    return height;
}
int dp_check_proof_node(const Board&b,ProofCheck&check,int depth,const Board*template_board=nullptr) {
    tick();const auto k=key(b,0);
    auto completed=check.completed.find(k);if(completed!=check.completed.end())return completed->second;
    if(check.path.count(k)){++check.cycles;return -1;}
    Board source=template_board?*template_board:b;
    // An exact target witness is independent of the incoming template.
    if(dp_proofs.find(k)!=dp_proofs.end())source=b;
    const ProofPair pair{k,key(source,0)};
    auto done=check.heights.find(pair);if(done!=check.heights.end())return done->second;
    if(depth>dp_max_depth){check.limited=true;if(check.limit_reason.empty())check.limit_reason="depth";return -1;}
    if(check.checked_pairs>=dp_proof_cap){check.limited=true;if(check.limit_reason.empty())check.limit_reason="target_source_pairs";return -1;}
    ++check.checked_pairs;
    if(!proof_hand_dominates(b,source)){
        ++check.invalid;check.heights[pair]=-1;return -1;}
    auto f=dp_proofs.find(pair.source);
    if(f==dp_proofs.end()){
        ++check.missing;
        if(check.missing_examples.size()<8){check.missing_examples.push_back(b.sfen());check.missing_source_examples.push_back(source.sfen());}
        check.heights[pair]=-1;return -1;
    }
    ++check.visited;const auto&node=f->second;
    if(node.floor!=dp_proof_floor||!proof_same_position(source,Board::parse(node.position))){
        ++check.invalid;check.heights[pair]=-1;return -1;}
    const bool adapted=!proof_same_position(b,source);
    if(adapted)++check.adaptation_visits;
    check.path.insert(k);bool valid=true;int height=0;
    ProofNode materialized;materialized.position=b.sfen();materialized.adapted_from=source.sfen();
    materialized.prune=node.prune;materialized.chain=node.chain;materialized.floor=node.floor;
    // Historical reuse metadata belongs to the source node, not the new hands.
    std::vector<Move> reuse_moves;
    for(const auto&reuse:node.hand_reused){
        if(!proof_contains(node.moves,reuse.move)||proof_contains(reuse_moves,reuse.move)){
            ++check.invalid;valid=false;continue;}
        reuse_moves.push_back(reuse.move);
        if(!source.legal(reuse.move)){++check.invalid;valid=false;continue;}
        Board child=source;child.push(reuse.move);Board origin=Board::parse(reuse.source);
        if(!proof_hand_dominates(child,origin)){++check.invalid;valid=false;}
    }
    if(b.turn==0) {
        if(node.moves.size()!=1||!node.omitted.empty()){++check.invalid;valid=false;}
        else {
            const auto&m=node.moves[0];
            if(!source.legal(m)||!b.legal(m)){++check.invalid;valid=false;}
            else {Board child=b,source_child=source;child.push(m);source_child.push(m);
                if(!child.check()||!source_child.check()){++check.invalid;valid=false;}
                else {int h=dp_check_proof_child(child,source_child,node,m,check,depth+1);
                    if(h<0)valid=false;else height=h+1;materialized.moves.push_back(m);}}
        }
    } else {
        if(!b.check()||!source.check()){++check.invalid;valid=false;}
        std::vector<Move> normal,drops;int attacker;evasions_split(b,normal,drops,attacker);
        std::vector<Move> raw=normal;raw.insert(raw.end(),drops.begin(),drops.end());
        std::vector<Move> source_normal,source_drops;
        if(adapted)evasions_split(source,source_normal,source_drops,attacker);
        else{source_normal=normal;source_drops=drops;}
        std::vector<Move> source_raw=source_normal;source_raw.insert(source_raw.end(),source_drops.begin(),source_drops.end());
        std::vector<Move> covered;
        // Validate the template itself locally before dropping unavailable replies.
        for(const auto&m:node.moves){
            if(!proof_contains(source_raw,m)||proof_contains(covered,m)){++check.invalid;valid=false;continue;}
            covered.push_back(m);
        }
        for(const auto&omission:node.omitted){const auto&m=omission.move;
            if(!proof_omission_allowed(source,m,source_normal,source_drops,node)||proof_contains(covered,m)){
                ++check.invalid;valid=false;continue;}
            covered.push_back(m);
        }
        if(covered.size()!=source_raw.size()){++check.invalid;valid=false;}
        for(const auto&m:source_raw)if(!proof_contains(raw,m))++check.ignored_source_defenses;
        for(const auto&m:raw) {
            if(proof_contains(node.moves,m)){
                Board child=b,source_child=source;child.push(m);source_child.push(m);
                int h=dp_check_proof_child(child,source_child,node,m,check,depth+1);
                if(h<0)valid=false;else height=std::max(height,h+1);
                materialized.moves.push_back(m);
            } else {
                bool omitted=false;for(const auto&o:node.omitted)if(proof_same_move(o.move,m)){omitted=true;break;}
                if(!omitted){++check.uncovered_defenses;++check.invalid;valid=false;continue;}
                if(!proof_omission_allowed(b,m,normal,drops,node)){++check.invalid;valid=false;continue;}
                ++check.pending;if(check.pending_defenses.size()<16)check.pending_defenses.push_back({b.sfen(),m.usi()});materialized.omitted.push_back({m});
            }
        }
    }
    check.path.erase(k);
    if(valid&&adapted&&dp_adapted_proofs.find(k)==dp_adapted_proofs.end()){
        const size_t edges=materialized.moves.size()+materialized.omitted.size();
        if(dp_adapted_proofs.size()>=dp_proof_cap||dp_adapted_edges+edges>dp_proof_edge_cap){
            check.limited=true;valid=false;
            if(check.limit_reason.empty())check.limit_reason=dp_adapted_proofs.size()>=dp_proof_cap?"adapted_nodes":"adapted_edges";
        } else {dp_adapted_edges+=edges;dp_adapted_proofs.emplace(k,std::move(materialized));}
    }
    check.heights[pair]=valid?height:-1;
    if(valid)check.completed.emplace(k,height);
    return valid?height:-1;
}
static std::string proof_json_string(const std::string&s) {
    const char* hex="0123456789abcdef";std::string out="\"";
    for(unsigned char c:s){if(c=='"'||c=='\\'){out+='\\';out+=char(c);}
        else if(c<32){out+="\\u00";out+=hex[c>>4];out+=hex[c&15];}else out+=char(c);}
    out+='"';return out;
}
std::string dp_proof_report() {
    dp_adapted_proofs.clear();dp_adapted_edges=0;ProofCheck check;int height=-1;
    bool settings_match=futile_floor==dp_proof_floor;
    if(dp_proof_result=="mate"&&settings_match&&!dp_proof_root.empty())
        height=dp_check_proof_node(Board::parse(dp_proof_root),check,0);
    const bool complete=dp_proof_result=="mate"&&settings_match&&height>=0&&!check.limited;
    dp_last_proof_complete=complete;dp_last_proof_pending=check.pending;
    std::string out="{\"result\":"+proof_json_string(dp_proof_result)+
        ",\"root\":"+proof_json_string(dp_proof_root)+
        ",\"recorded_nodes\":"+std::to_string(dp_proofs.size())+
        ",\"recorded_edges\":"+std::to_string(dp_proof_edges)+
        ",\"record_limit_reached\":"+(dp_proof_truncated?"true":"false")+
        ",\"settings_match\":"+(settings_match?"true":"false")+
        ",\"structurally_complete\":"+(complete?"true":"false")+
        ",\"complete_without_omissions\":"+(complete&&check.pending==0?"true":"false")+
        ",\"visited_nodes\":"+std::to_string(check.visited)+
        ",\"missing_nodes\":"+std::to_string(check.missing)+
        ",\"invalid_nodes\":"+std::to_string(check.invalid)+
        ",\"cycles\":"+std::to_string(check.cycles)+
        ",\"pending_omissions\":"+std::to_string(check.pending)+
        ",\"hand_reused_edges\":"+std::to_string(check.hand_reused)+
        ",\"missing_hand_reuse_children\":"+std::to_string(check.hand_missing)+
        ",\"hand_reuse_resolved\":"+std::to_string(check.hand_resolved)+
        ",\"adapted_nodes\":"+std::to_string(dp_adapted_proofs.size())+
        ",\"adaptation_visits\":"+std::to_string(check.adaptation_visits)+
        ",\"checked_pairs\":"+std::to_string(check.checked_pairs)+
        ",\"adapted_edges\":"+std::to_string(dp_adapted_edges)+
        ",\"check_limit_reason\":"+proof_json_string(check.limit_reason)+
        ",\"record_node_limit\":"+std::to_string(dp_proof_cap)+
        ",\"record_edge_limit\":"+std::to_string(dp_proof_edge_cap)+
        ",\"check_pair_limit\":"+std::to_string(dp_proof_cap)+
        ",\"ignored_source_defenses\":"+std::to_string(check.ignored_source_defenses)+
        ",\"uncovered_defenses\":"+std::to_string(check.uncovered_defenses)+
        ",\"check_limit_reached\":"+(check.limited?"true":"false")+
        ",\"recorded_tree_height\":"+std::to_string(height)+
        ",\"mate_length_verified\":false,\"strict_result_reused\":false,\"missing_examples\":[";
    bool comma=false;for(const auto&s:check.missing_examples){if(comma)out+=',';comma=true;out+=proof_json_string(s);}
    out+= "],\"missing_source_examples\":[";comma=false;
    for(const auto&s:check.missing_source_examples){if(comma)out+=',';comma=true;out+=proof_json_string(s);}
    out+="],\"pending_defenses\":[";comma=false;
    for(const auto&request:check.pending_defenses){if(comma)out+=',';comma=true;
        out+="{\"sfen\":"+proof_json_string(request.first)+",\"move\":"+proof_json_string(request.second)+"}";}
    return out+"]}";
}
std::string proof_node_json(const ProofNode&node) {
    std::string out="{\"sfen\":"+proof_json_string(node.position)+",\"adapted_from\":"+proof_json_string(node.adapted_from)+
        ",\"prune\":"+std::to_string(node.prune)+",\"chain\":"+std::to_string(node.chain)+
        ",\"floor\":"+std::to_string(node.floor)+",\"moves\":[";bool sep=false;
    for(const auto&m:node.moves){if(sep)out+=',';sep=true;out+=proof_json_string(m.usi());}
    out+="],\"omitted\":[";sep=false;
    for(const auto&m:node.omitted){if(sep)out+=',';sep=true;out+="{\"move\":"+proof_json_string(m.move.usi())+
        ",\"reason\":\"unprotected_distant_drop\",\"verified_futile\":false}";}
    out+="],\"hand_reused\":[";sep=false;
    for(const auto&reuse:node.hand_reused){if(sep)out+=',';sep=true;
        out+="{\"move\":"+proof_json_string(reuse.move.usi())+",\"source_sfen\":"+proof_json_string(reuse.source)+"}";}
    return out+"]}";
}
std::string dp_proof_export() {
    std::string out="{\"format\":2,\"root\":"+proof_json_string(dp_proof_root)+
        ",\"result\":"+proof_json_string(dp_proof_result)+",\"nodes\":[";bool comma=false;
    for(const auto&entry:dp_proofs){tick();if(comma)out+=',';comma=true;out+=proof_node_json(entry.second);}
    out+="],\"adapted_nodes\":[";comma=false;
    for(const auto&entry:dp_adapted_proofs){tick();if(comma)out+=',';comma=true;out+=proof_node_json(entry.second);}
    return out+"]}";
}
std::string dfpn_record(const Board&b,int max_nodes) {
    dp_proof_clear();dp_proof_cap=size_t(std::max(1,std::min(max_nodes,100000)));
    dp_proof_edge_cap=dp_proof_cap*4;dp_proof_root=b.sfen();dp_proof_floor=futile_floor;
    dp_proof_root_key=key(b,0);dp_proof_result="searching";dp_proof_recording=true;
    uint64_t pn=1,dn=1;
    try {dp_portfolio(b,pn,dn);dp_proof_recording=false;
        dp_proof_result=pn==0?"mate":dn==0&&!dp_deep?"nomate":"unknown";
    } catch(...) {dp_proof_recording=false;dp_proof_result="interrupted";throw;}
    // The report/checker must work after the numerical search table is gone.
    dpt.clear();dpath.clear();dp_prune=1;dp_chain=1;
    return dp_proof_report();
}
