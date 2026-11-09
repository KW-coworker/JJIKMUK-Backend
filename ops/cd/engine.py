"""One bounded JAR-only deployment. The host persists intent before every transition."""


def deploy(host, request):
    existing = host.existing(request)
    if existing: return existing
    previous = host.baseline
    candidate = host.prepare(request)
    host.preflight(previous, candidate)
    old_identity = host.identity()
    host.transition = {'previous': previous, 'candidate': candidate}
    host.record(request, 'SWITCH_INTENT')
    try:
        host.activate(candidate)
        host.restart()
        host.verify(candidate, old_identity)
        host.commit(candidate)
        host.record(request, 'SUCCEEDED')
    except Exception as error:
        from notices import REASONS
        host.failure_reason = str(error) if str(error) in REASONS else 'REVIEW_REQUIRED'
        # A failure after intent may have switched the pointer, including restart failure.
        try:
            host.record(request, 'ROLLBACK_INTENT')
            host.rollback_preflight(previous, candidate)
            old_identity = host.identity()
            host.activate(previous)
            host.restart()
            host.verify(previous, old_identity)
            host.commit(previous)
            host.record(request, 'ROLLED_BACK')
        except Exception:
            host.record(request, 'MANUAL_RECOVERY_REQUIRED')
    return host.journal
