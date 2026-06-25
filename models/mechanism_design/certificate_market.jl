# Truth-certificate payout checks for PopperPad.
#
# The doctrine is: payment can fund proof work, but only verifier-accepted
# certificates make work payable.

struct CertificateCase
    name::String
    payment_offered::Float64
    verifier_accepted::Bool
    certificate_available::Bool
    challenge_failed::Bool
    expected_payable::Bool
end

function certificate_payable(c::CertificateCase)::Bool
    return c.payment_offered > 0 &&
        c.verifier_accepted &&
        c.certificate_available &&
        !c.challenge_failed
end

function passfail(ok::Bool)::String
    return ok ? "PASS" : "FAIL"
end

function print_certificate_report(cases::Vector{CertificateCase})::Bool
    println("Truth certificate payout checks")
    println("case, payment_offered, verifier_accepted, certificate_available, challenge_failed, payable, verdict")
    all_ok = true
    for c in cases
        payable = certificate_payable(c)
        ok = payable == c.expected_payable
        all_ok &= ok
        println(join((
            c.name,
            round(c.payment_offered; digits = 4),
            c.verifier_accepted,
            c.certificate_available,
            c.challenge_failed,
            payable,
            passfail(ok),
        ), ", "))
    end
    println()
    return all_ok
end

cases = CertificateCase[
    CertificateCase("lean_proof_certificate", 1_000.0, true, true, false, true),
    CertificateCase("paid_unchecked_assertion", 1_000.0, false, true, false, false),
    CertificateCase("accepted_but_unavailable_certificate", 500.0, true, false, false, false),
    CertificateCase("successful_challenge_blocks_payout", 500.0, true, true, true, false),
    CertificateCase("no_bounty_no_market_payout", 0.0, true, true, false, false),
]

ok = print_certificate_report(cases)

if !ok
    exit(1)
end

println("All modeled truth-certificate payout checks pass.")
