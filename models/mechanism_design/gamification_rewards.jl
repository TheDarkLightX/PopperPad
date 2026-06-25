# Gamification reward checks for PopperPad.
#
# The model keeps points playful but verifier-gated, and keeps token rewards
# tied to work value, costs, and public-good subsidy.

struct ScoreCase
    name::String
    base_points::Float64
    verifier_weight::Float64
    novelty_weight::Float64
    reproducibility_weight::Float64
    difficulty_weight::Float64
    domain_need_weight::Float64
    duplicate_penalty::Float64
    sybil_penalty::Float64
    flakiness_penalty::Float64
    verifier_accepted::Bool
end

struct TokenRewardCase
    name::String
    work_value::Float64
    cost_reimbursement::Float64
    public_good_subsidy::Float64
    challenge_risk_discount::Float64
    verifier_accepted::Bool
end

struct QuestCompletionCase
    name::String
    accepted_event_kind::Bool
    evidence_count::Int
    required_evidence_count::Int
    sybil_risk::Float64
    max_sybil_risk::Float64
end

function score_delta(c::ScoreCase)::Float64
    if !c.verifier_accepted
        return 0.0
    end
    raw = c.base_points *
        c.verifier_weight *
        c.novelty_weight *
        c.reproducibility_weight *
        c.difficulty_weight *
        c.domain_need_weight
    return max(0.0, raw - c.duplicate_penalty - c.sybil_penalty - c.flakiness_penalty)
end

function token_reward(c::TokenRewardCase)::Float64
    if !c.verifier_accepted
        return 0.0
    end
    return max(0.0, c.work_value + c.cost_reimbursement + c.public_good_subsidy - c.challenge_risk_discount)
end

function quest_completion_eligible(c::QuestCompletionCase)::Bool
    return c.accepted_event_kind &&
        c.evidence_count >= c.required_evidence_count &&
        c.sybil_risk <= c.max_sybil_risk
end

function passfail(ok::Bool)::String
    return ok ? "PASS" : "FAIL"
end

function print_score_report(cases::Vector{ScoreCase})::Bool
    println("Gamification score checks")
    println("case, verifier_accepted, score_delta, verdict")
    all_ok = true
    for c in cases
        score = score_delta(c)
        ok = c.verifier_accepted ? score > 0 : score == 0
        all_ok &= ok
        println(join((c.name, c.verifier_accepted, round(score; digits = 4), passfail(ok)), ", "))
    end
    println()
    return all_ok
end

function print_token_reward_report(cases::Vector{TokenRewardCase})::Bool
    println("Gamified token reward checks")
    println("case, verifier_accepted, token_reward, verdict")
    all_ok = true
    for c in cases
        reward = token_reward(c)
        ok = c.verifier_accepted ? reward > 0 : reward == 0
        all_ok &= ok
        println(join((c.name, c.verifier_accepted, round(reward; digits = 4), passfail(ok)), ", "))
    end
    println()
    return all_ok
end

function print_quest_completion_report(cases::Vector{QuestCompletionCase})::Bool
    println("Quest completion checks")
    println("case, accepted_event_kind, evidence_count, sybil_risk, eligible, verdict")
    all_ok = true
    for c in cases
        eligible = quest_completion_eligible(c)
        expected = c.name == "valid_proof_quest_completion"
        ok = eligible == expected
        all_ok &= ok
        println(join((
            c.name,
            c.accepted_event_kind,
            c.evidence_count,
            round(c.sybil_risk; digits = 4),
            eligible,
            passfail(ok),
        ), ", "))
    end
    println()
    return all_ok
end

score_cases = ScoreCase[
    ScoreCase("lean_proof_accepted", 100.0, 1.5, 1.2, 1.0, 1.4, 1.3, 0.0, 5.0, 0.0, true),
    ScoreCase("counterexample_minimized", 120.0, 1.4, 1.5, 1.1, 1.2, 1.1, 10.0, 3.0, 2.0, true),
    ScoreCase("low_value_reproduction", 40.0, 1.0, 0.4, 0.8, 0.8, 0.9, 4.0, 0.0, 0.0, true),
    ScoreCase("unsupported_claim_popular", 500.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, false),
]

token_cases = TokenRewardCase[
    TokenRewardCase("proof_bounty", 80.0, 15.0, 20.0, 5.0, true),
    TokenRewardCase("storage_retrieval_streak", 12.0, 8.0, 4.0, 2.0, true),
    TokenRewardCase("unsupported_popularity_reward", 1_000.0, 0.0, 0.0, 0.0, false),
]

quest_cases = QuestCompletionCase[
    QuestCompletionCase("valid_proof_quest_completion", true, 1, 1, 0.03, 0.20),
    QuestCompletionCase("missing_evidence", true, 0, 1, 0.01, 0.20),
    QuestCompletionCase("wrong_event_kind", false, 2, 1, 0.01, 0.20),
    QuestCompletionCase("sybil_cluster", true, 2, 1, 0.65, 0.20),
]

scores_ok = print_score_report(score_cases)
tokens_ok = print_token_reward_report(token_cases)
quests_ok = print_quest_completion_report(quest_cases)

if !(scores_ok && tokens_ok && quests_ok)
    exit(1)
end

println("All modeled gamification reward checks pass.")
