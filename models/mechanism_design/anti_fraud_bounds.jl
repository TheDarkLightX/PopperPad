# Deterministic mechanism-design checks for PopperPad's falsification market.
#
# The numbers here are not launch tokenomics. They are executable sanity checks
# for whether a proposed parameter profile satisfies the basic AGT inequalities.

struct FraudCase
    name::String
    defect_gain::Float64
    detection_probability::Float64
    slash_amount::Float64
    future_value_lost::Float64
end

struct HonestWork
    name::String
    reward::Float64
    reputation_value::Float64
    cost::Float64
    slash_probability::Float64
    bond::Float64
end

function deterrence(c::FraudCase)::Float64
    return c.detection_probability * c.slash_amount + c.future_value_lost
end

function fraud_margin(c::FraudCase)::Float64
    return c.defect_gain - deterrence(c)
end

function required_slash_amount(c::FraudCase)::Float64
    residual = c.defect_gain - c.future_value_lost
    if residual <= 0
        return 0.0
    end
    if c.detection_probability <= 0
        return Inf
    end
    return residual / c.detection_probability
end

function honest_expected_payoff(w::HonestWork)::Float64
    return w.reward + w.reputation_value - w.cost - w.slash_probability * w.bond
end

function passfail(ok::Bool)::String
    return ok ? "PASS" : "FAIL"
end

function print_fraud_report(cases::Vector{FraudCase})::Bool
    println("Fraud deterrence checks")
    println("case, defect_gain, deterrence, margin, min_slash, verdict")
    all_ok = true
    for c in cases
        margin = fraud_margin(c)
        ok = margin <= 0
        all_ok &= ok
        println(join((
            c.name,
            round(c.defect_gain; digits = 4),
            round(deterrence(c); digits = 4),
            round(margin; digits = 4),
            round(required_slash_amount(c); digits = 4),
            passfail(ok),
        ), ", "))
    end
    println()
    return all_ok
end

function print_honest_work_report(work::Vector{HonestWork})::Bool
    println("Honest work participation checks")
    println("case, reward, reputation_value, cost, expected_payoff, verdict")
    all_ok = true
    for w in work
        payoff = honest_expected_payoff(w)
        ok = payoff > 0
        all_ok &= ok
        println(join((
            w.name,
            round(w.reward; digits = 4),
            round(w.reputation_value; digits = 4),
            round(w.cost; digits = 4),
            round(payoff; digits = 4),
            passfail(ok),
        ), ", "))
    end
    println()
    return all_ok
end

fraud_cases = FraudCase[
    FraudCase("fake_counterexample", 700.0, 0.72, 900.0, 150.0),
    FraudCase("fake_attestation", 120.0, 0.45, 180.0, 65.0),
    FraudCase("fake_storage_claim", 80.0, 0.35, 150.0, 40.0),
    FraudCase("duplicate_as_novel", 250.0, 0.65, 260.0, 90.0),
]

honest_work = HonestWork[
    HonestWork("counterexample_search", 900.0, 120.0, 460.0, 0.01, 200.0),
    HonestWork("independent_reproduction_fail", 210.0, 45.0, 130.0, 0.005, 80.0),
    HonestWork("recipe_maintenance", 360.0, 80.0, 240.0, 0.005, 100.0),
    HonestWork("artifact_storage_epoch", 95.0, 20.0, 55.0, 0.02, 120.0),
]

fraud_ok = print_fraud_report(fraud_cases)
honest_ok = print_honest_work_report(honest_work)

if !(fraud_ok && honest_ok)
    exit(1)
end

println("All modeled mechanism-design inequalities pass.")
