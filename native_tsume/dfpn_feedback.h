// Included inside Solver. First, bounded strict-to-df-pn repair requests.
std::unique_ptr<Solver> dp_feedback_worker;
bool dp_install_required(const Board&b,const Move&m) {
    if(dp_defense_required(b,m))return false;
    if(dp_required_count>=4096)throw std::runtime_error("Too many required defenses");
    dp_required_defenses[dp_required_key(b)].push_back(m);++dp_required_count;
    // All numerical values were computed under the previous inclusion policy.
    dpt.clear();dpath.clear();dp_ent=0;dpl_memo.clear();dpl_path.clear();
    dp_adapted_proofs.clear();dp_adapted_edges=0;dp_last_proof_complete=false;
    return true;
}
bool dp_merge_feedback_records(const Solver&worker) {
    if(!dp_proof_root.empty()&&dp_proof_floor!=futile_floor)return false;
    auto combined=dp_proofs;
    for(const auto&entry:worker.dp_proofs){combined[entry.first]=entry.second;if(combined.size()>dp_proof_cap)return false;}
    for(const auto&entry:worker.dp_adapted_proofs){combined[entry.first]=entry.second;if(combined.size()>dp_proof_cap)return false;}
    size_t edges=0;for(const auto&entry:combined){edges+=entry.second.moves.size()+entry.second.omitted.size();if(edges>dp_proof_edge_cap)return false;}
    dp_proofs.swap(combined);dp_proof_edges=edges;dp_adapted_proofs.clear();dp_adapted_edges=0;
    dp_proof_truncated|=worker.dp_proof_truncated;
    if(dp_proof_root.empty()){
        dp_proof_root=worker.dp_proof_root;dp_proof_root_key=worker.dp_proof_root_key;
        dp_proof_floor=futile_floor;dp_proof_result=worker.dp_proof_result;
    }
    dp_last_proof_complete=false;return true;
}
std::string dfpn_repair_defense(const Board&b,const Move&m,int strict_budget,int max_nodes) {
    if(b.turn!=1||!b.check()||strict_budget<0)throw std::invalid_argument("Checked defender position and nonnegative budget required");
    std::vector<Move> normal,drops;int attacker;evasions_split(b,normal,drops,attacker);
    if(!proof_contains(drops,m)||!b.legal(m))throw std::invalid_argument("A legal interposition is required");
    if(futile(b,m,attacker,strict_budget))
        return "{\"status\":\"not_needed\",\"strict_futile\":true,\"strict_result_reused\":false}";
    const bool added=dp_install_required(b,m);
    auto worker=std::make_unique<Solver>();worker->futile_floor=futile_floor;
    worker->dp_max_depth=dp_max_depth;worker->dp_cap=dp_cap;
    worker->dp_required_defenses=dp_required_defenses;worker->dp_required_count=dp_required_count;
    worker->timed=timed;worker->deadline=deadline;
    std::vector<DItem> included;worker->dp_items(b,included);bool found=false;
    for(const auto&item:included){if(proof_same_move(item.m,m))found=true;for(const auto&rest:item.rest)if(proof_same_move(rest,m))found=true;}
    if(!found)throw std::runtime_error("Required defense was not generated");
    std::string proof;
    try{proof=worker->dfpn_record(b,max_nodes);}
    catch(const Timeout&){
        if(g_cancel.load(std::memory_order_relaxed))throw;
        worker->dp_proof_recording=false;worker->dp_proof_result="interrupted";
        worker->dpt.clear();worker->dpath.clear();worker->dp_ent=0;
        proof=worker->dp_proof_report();
    }
    worker->timed=false;
    bool required_proved=false;
    auto root=worker->dp_proofs.find(worker->key(b,0));
    if(root!=worker->dp_proofs.end())required_proved=proof_contains(root->second.moves,m);
    const bool ready=worker->dp_proof_result=="mate"&&worker->dp_last_proof_complete&&required_proved;
    bool merged=false;if(ready)merged=dp_merge_feedback_records(*worker);
    std::string status=ready?"mate_proof":worker->dp_proof_result=="nomate"?"nomate_candidate":worker->dp_proof_result=="mate"?"incomplete_proof":"unknown";
    std::string out="{\"status\":"+proof_json_string(status)+
        ",\"strict_futile\":false,\"strict_checked_budget\":"+std::to_string(strict_budget)+
        ",\"required_move\":"+proof_json_string(m.usi())+
        ",\"constraint_added\":"+(added?"true":"false")+
        ",\"required_included\":true,\"required_branch_proved\":"+(required_proved?"true":"false")+
        ",\"records_merged\":"+(merged?"true":"false")+
        ",\"original_proof_recheck_required\":true,\"original_numeric_cache_reused\":false,\"strict_result_reused\":false,\"proof\":"+proof+"}";
    dp_feedback_worker=std::move(worker);return out;
}
std::string dp_export_feedback() {
    if(!dp_feedback_worker)return "{\"format\":2,\"result\":\"none\",\"nodes\":[],\"adapted_nodes\":[]}";
    dp_feedback_worker->timed=timed;dp_feedback_worker->deadline=deadline;
    try{auto result=dp_feedback_worker->dp_proof_export();dp_feedback_worker->timed=false;return result;}
    catch(...){dp_feedback_worker->timed=false;throw;}
}
