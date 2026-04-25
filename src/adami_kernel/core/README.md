## Purpose

`core/` owns **process boot** and **runtime lifecycle** wiring. It composes initialized components (router, memory, bus, planner, workflow engine, nerves) into a running kernel and defines concurrency boundaries for event consumption.

## Key files

- `boot_manager.py`: boot sequencing (Web Console startup, injection, skill metadata warm-up).
- `component_initializer.py`: constructs the component graph (dependency injection / late imports).
- `lifecycle_manager.py`: runs the main loop, consumes `system.events`, and hosts runtime proxies.
- `kernel_context.py`: explicit `KernelContext` protocol (contract between core and cortex/orchestrator).

## Primary flows

- **Boot**: `kernel.py` → `BootManager.boot()` (starts web console, initializes engines)
- **Runtime**: `LifecycleManager.run_forever()` → event consumer with bounded concurrency

## Operational notes

- If you change cross-module dependencies, prefer updating `component_initializer.py` to keep wiring centralized.

