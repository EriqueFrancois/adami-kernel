flowchart TB
  %% AdamI Kernel — Multi-Agent Orchestration Flow
  %% Subtitle: First-run initializer blocks boot until required config is set

  subgraph Gate[First-run init (CLI wizard)]
    direction TB
    G1[Language]
    G2[Runtime profile]
    G3[Local LLM (required fallback)]
    G4[Cloud key (≥1)]
    G5[Telegram/Discord (≥1)]
    G6[Observability]
  end

  subgraph Inputs[Inputs]
    direction TB
    CLI[CLI]
    WEB[Web Console]
    TG[Telegram]
    DC[Discord]
  end

  Gate -. must complete before boot .-> BootNote[(Refuses to boot\nuntil initialization is complete)]

  Inputs --> EB[EventBus]
  EB --> LM[LifecycleManager\n(bounded concurrency)]
  BootNote -. gate .-> LM

  LM --> DP[DecisionProcessor\n(intent routing)]

  DP -->|simple/known| Templates[Intent Templates\n(optional tiers)]
  DP -->|complex| Planner[Planner\n(plan + execute)]
  Planner --> Composer[SkillComposer\n(build DAG)]
  Composer --> Engine[WorkflowEngine\n(execute DAG)]
  Engine --> Memory[LayeredMemory\n(persist state/experience)]
  Engine --> Tools[Tools / Skills\n(WebTool, LLM, Sandboxes, …)]

  Obs[Observability\n(OTel traces/metrics)]
  LM --> Obs
  DP --> Obs
  Engine --> Obs
