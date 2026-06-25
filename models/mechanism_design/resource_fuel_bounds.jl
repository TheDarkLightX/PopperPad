# Resource-fuel checks for PopperPad's token-powered network economy.
#
# These checks are intentionally small and deterministic. They encode the design
# rule that resources must be funded while local scientific status remains
# independent of stake.

struct ResourceTask
    name::String
    funded_budget::Float64
    compute_cost::Float64
    storage_cost::Float64
    api_cost::Float64
    verifier_cost::Float64
    retrieval_cost::Float64
end

struct TreasuryEpoch
    name::String
    starting_balance::Float64
    inflows::Float64
    committed_outflows::Float64
    reserve_requirement::Float64
end

struct EarnPath
    name::String
    earned_credits::Float64
    minimum_agent_run_cost::Float64
end

function task_cost(t::ResourceTask)::Float64
    return t.compute_cost + t.storage_cost + t.api_cost + t.verifier_cost + t.retrieval_cost
end

function budget_margin(t::ResourceTask)::Float64
    return t.funded_budget - task_cost(t)
end

function treasury_margin(e::TreasuryEpoch)::Float64
    return e.starting_balance + e.inflows - e.committed_outflows - e.reserve_requirement
end

function earn_margin(p::EarnPath)::Float64
    return p.earned_credits - p.minimum_agent_run_cost
end

function passfail(ok::Bool)::String
    return ok ? "PASS" : "FAIL"
end

function print_resource_task_report(tasks::Vector{ResourceTask})::Bool
    println("Resource budget checks")
    println("case, funded_budget, total_cost, margin, verdict")
    all_ok = true
    for t in tasks
        margin = budget_margin(t)
        ok = margin >= 0
        all_ok &= ok
        println(join((
            t.name,
            round(t.funded_budget; digits = 4),
            round(task_cost(t); digits = 4),
            round(margin; digits = 4),
            passfail(ok),
        ), ", "))
    end
    println()
    return all_ok
end

function print_treasury_report(epochs::Vector{TreasuryEpoch})::Bool
    println("Treasury solvency checks")
    println("case, starting_balance, inflows, outflows, reserve, margin, verdict")
    all_ok = true
    for e in epochs
        margin = treasury_margin(e)
        ok = margin >= 0
        all_ok &= ok
        println(join((
            e.name,
            round(e.starting_balance; digits = 4),
            round(e.inflows; digits = 4),
            round(e.committed_outflows; digits = 4),
            round(e.reserve_requirement; digits = 4),
            round(margin; digits = 4),
            passfail(ok),
        ), ", "))
    end
    println()
    return all_ok
end

function print_earn_path_report(paths::Vector{EarnPath})::Bool
    println("Earn-before-spend access checks")
    println("case, earned_credits, minimum_agent_run_cost, margin, verdict")
    all_ok = true
    for p in paths
        margin = earn_margin(p)
        ok = margin >= 0
        all_ok &= ok
        println(join((
            p.name,
            round(p.earned_credits; digits = 4),
            round(p.minimum_agent_run_cost; digits = 4),
            round(margin; digits = 4),
            passfail(ok),
        ), ", "))
    end
    println()
    return all_ok
end

tasks = ResourceTask[
    ResourceTask("counterexample_agent_run", 60.0, 12.0, 2.5, 30.0, 8.0, 3.0),
    ResourceTask("reproduction_agent_run", 18.0, 4.0, 1.0, 8.0, 3.0, 1.0),
    ResourceTask("storage_epoch_high_value_bundle", 25.0, 0.5, 14.0, 0.0, 0.0, 4.0),
]

epochs = TreasuryEpoch[
    TreasuryEpoch("public_good_epoch_001", 1_000.0, 380.0, 910.0, 250.0),
    TreasuryEpoch("storage_subsidy_epoch_001", 500.0, 160.0, 420.0, 180.0),
]

earn_paths = EarnPath[
    EarnPath("local_reproduction_reward", 12.0, 8.0),
    EarnPath("artifact_mirror_reward", 6.5, 4.0),
    EarnPath("recipe_maintenance_reward", 35.0, 18.0),
]

tasks_ok = print_resource_task_report(tasks)
treasury_ok = print_treasury_report(epochs)
earn_ok = print_earn_path_report(earn_paths)

if !(tasks_ok && treasury_ok && earn_ok)
    exit(1)
end

println("All modeled resource-fuel inequalities pass.")
