# Learning Service

The **Learning Service** is Renova’s **executor/agent service**.  
It runs capability packs + playbooks against a workspace and produces CAM artifacts.

---

## Purpose

- Orchestrates a **plan → act → validate → persist/classify/publish** loop.
- Integrates with **external tools** (COBOL parsers, JCL analyzers, DB2 analyzers, GitHub fetchers, etc.).
- Invokes **LLM agents** to synthesize artifacts when tools aren’t enough.
- Persists results to the **artifact-service** and publishes lifecycle events to **RabbitMQ**.

---

## Execution Flow

The orchestration graph (`learning_graph.py`) wires nodes in sequence:

1. **ingest_node**  
   Loads the capability pack + selected playbook from the registry. Seeds `plan`.

2. **plan_node**  
   Normalizes steps. Optionally calls LLM provider to enrich step `params`.

3. **resolve_dependencies_node**  
   Looks up emitted kinds in the kind registry.  
   Builds a `dep_plan` of `hard` and `soft` dependencies + `context_hint`.

4. **tool_exec_node**  
   Executes all `tool_call` steps using `tool_runner`.  
   Threads extras (e.g. `repo_path`) between steps. Emits raw artifacts and `tool_outputs`.

5. **artifact_assembly_node**  
   (Optional) Normalization/shaping stage. Currently pass-through.

6. **context_assembly_node**  
   Runs **after tools** to materialize dependency context for each step:  
   - Prefers artifacts from the current run.  
   - Falls back to baseline workspace artifacts.  
   - Caps items per kind to keep prompts bounded.  
   - Attaches `context_hint` strings.

7. **agent_synthesize_node**  
   Executes all `capability` steps via `GenericKindAgent` (LLM).  
   Provides a context bundle (`avc`, `fss`, `pss`, produced artifacts, related inputs, tool_outputs).  
   Emits synthesized artifacts.

8. **validate_node**  
   Runs validator prompt over all artifacts. Produces structured issues.

> **Persist, classify, and publish happen in `main.py` after the graph finishes.**  
> This ensures the orchestration graph stays pure (no side effects).

---

## Key Design Points

- **Executor provides runtime config** (URLs, landing zone) at execution time.  
  Capability packs remain environment-agnostic.

- **Dependencies are first-class**: artifact kinds declare `depends_on` in the registry.  
  Agents automatically receive hard/soft context and hints.

- **Split responsibilities**:  
  - `tool_exec_node`: external tool adapters.  
  - `artifact_assembly_node`: optional shaping.  
  - `agent_synthesize_node`: LLM-based generation.  
  This separation makes the flow more debuggable and testable.

- **Resilient fallbacks**:  
  - If no tools run, agents still emit skeleton artifacts.  
  - If LLMs are disabled, deterministic placeholders are produced.

---

## Endpoints

- `POST /learn/{workspace_id}`  
  Starts a new learning run. Asynchronous; persists run record.  

- `GET /runs/{run_id}`  
  Fetch a specific run (status, summary, artifacts_diff).

- `GET /runs?workspace_id=...`  
  List runs for a workspace.

- `GET /health`  
  Health probe.

---

## Events

- `renova.learning-service.started.v1`  
- `renova.learning-service.completed.v1`  
- `renova.learning-service.failed.v1`

---

## Next Steps

- Expand **artifact_assembly_node** to normalize tool outputs into schema versions.  
- Implement stricter **validation rules** per kind.  
- Extend **tool_runner** with more adapters (e.g., PL/SQL, Java analyzers).  
- Add **consistency checks** for `hard` dependencies (diagram vs workflow node IDs).

---

## Diagrams

### Orchestration

```plantuml
@startuml
skinparam monochrome true
skinparam activity {
  BackgroundColor<<node>> #EFEFEF
  BorderColor<<node>> #999999
  RoundCorner 12
}
title Learning Service Orchestration (Plan → Act → Validate → Persist/Classify/Publish)

start

partition "Pack/Playbook" {
  :ingest_node;
}

partition "Planning" {
  :plan_node;
}

partition "Kind Dependencies" {
  :resolve_dependencies_node <<node>>;
}

partition "Execution (Tools → Agents)" {
  :tool_exec_node <<node>>;
  :artifact_assembly_node <<node>>;
  :context_assembly_node <<node>>;
  :agent_synthesize_node <<node>>;
}

partition "Quality" {
  :validate_node;
}

stop
@enduml

@startuml
skinparam monochrome true
title TOOL_EXEC step (runtime-configured)

actor "Learning Graph" as Orchestrator
participant "tool_exec_node" as ToolNode
participant "make_runtime_config()" as Runtime
participant "tool_runner.run_tool()" as Runner
participant "External Tool Service" as ToolSvc

Orchestrator -> ToolNode: step {type: tool_call, tool_key, params}
ToolNode -> Runtime: make_runtime_config(workspace)
Runtime --> ToolNode: runtime {connectors..., workspace...}

ToolNode -> Runner: run_tool(tool_key, params, runtime)
Runner -> ToolSvc: HTTP POST (connector base_url + endpoint)
ToolSvc --> Runner: {items, logs, extras}
Runner --> ToolNode: (artifacts, logs, extras)

ToolNode -> ToolNode: append artifacts, merge extras,\nstore tool_outputs[sid]
ToolNode --> Orchestrator: {artifacts +=, context{tool_extras, tool_outputs}}
@enduml

@startuml
skinparam monochrome true
title AGENT_SYNTHESIZE step (depends_on-aware)

actor "Learning Graph" as Orchestrator
participant "agent_synthesize_node" as AgentNode
collections "related[step_id]" as Related
participant "GenericKindAgent" as GKA
participant "LLM Provider" as LLM

Orchestrator -> AgentNode: step {type: capability, emits[kinds]}
AgentNode -> Related: load hard/soft artifacts\n(from run or baseline)
AgentNode -> GKA: run(ctx={artifacts, related, context_hint, tool_outputs}, params{kind})
GKA -> LLM: system+user prompt (JSON-only)\n(kind-aware, hint-aware)
LLM --> GKA: {kind, name, data}
GKA --> AgentNode: patches[{op: upsert, /artifacts, value:[...]}]

AgentNode -> AgentNode: append synthesized artifacts
AgentNode --> Orchestrator: {artifacts +=}
@enduml

