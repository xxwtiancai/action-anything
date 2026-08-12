"""A zero-dependency dry-run example."""

from actionanything import (
    Action,
    ActionKind,
    ActionRuntime,
    DryRunExecutor,
    PolicyEngine,
    RiskLevel,
    TraceRecorder,
)


runtime = ActionRuntime(
    executor=DryRunExecutor(),
    policy=PolicyEngine.standard(allowed_domains=["example.com"]),
    recorder=TraceRecorder("actionanything-trace.jsonl"),
)

result = runtime.execute(
    Action(
        kind=ActionKind.NAVIGATE,
        params={"url": "https://example.com"},
        risk=RiskLevel.READ_ONLY,
    )
)

print(result.to_dict())

