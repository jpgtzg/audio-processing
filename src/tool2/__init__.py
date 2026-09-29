"""Tool 2: finds embedded brand-mention "spots" inside content SARA's own
pipeline already discarded as non-commercial. See docs/handoff.md for the
current architecture and docs/progress.md for delivery history.

Split into submodules by concern:
    constants      -- discard/testigo status codes, env-configured settings
    logging_setup  -- the module logger + exception-detail formatting
    queries        -- all DB reads/writes (SEGMENTO_SARA, MENCIONES_COMERCIALES)
    crop           -- audio cropping/channel isolation
    pipeline       -- the per-segment transcribe + extract pipeline
    progress       -- last-processed-segment checkpoint state file, plus
                       per-segment completion tracking for one fetched batch
    service        -- orchestration: concurrent processing, the polling loop,
                       and the shared CLI entrypoint for run_tool2.py / `python -m src.tool2`

Re-exports the full previous flat-module API below so existing imports
(`from src.tool2 import X`) keep working unchanged."""
