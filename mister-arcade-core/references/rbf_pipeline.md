# From source to Arcade RBF

How a core's bitstream is produced, deployed and released, as the skill's scripts do it.
Every refusal box is a check that exists because its absence once cost a session; the
scripts' own headers say which.

```mermaid
flowchart TD
    subgraph BEFORE["Before the first build"]
        A["Bootstrap: new_core.py from Template_MiSTer"] --> B["Research: MAME driver, HARDWARE_NOTES.md,<br/>clock plan from ~48 MHz"]
        B --> C{"Roadmap approved<br/>by the user?"}
        C -- "no" --> B
        C -- "yes" --> D["RTL and benches:<br/>Verilator / ModelSim against MAME captures"]
    end

    D --> E["Commit to develop"]

    subgraph BUILD["scripts/build_staged.py"]
        E --> F{"Tree clean?"}
        F -- "no" --> F1["Refuse: commit first,<br/>the build is exactly HEAD"]
        F -- "yes" --> G{"hwlock: JTAG held<br/>or waiting?"}
        G -- "yes" --> G1["Refuse: JTAG has priority"]
        G -- "no" --> H{"Another staged<br/>build running?"}
        H -- "yes" --> H1["Refuse"]
        H -- "no" --> I["Worktree build/ reset to HEAD,<br/>SEED patched, BUILT_COMMIT written,<br/>STAGE_COPIES copied in"]
        I --> J["quartus_sh flow on the revision:<br/>Name_stp (DEBUG_ISSP) or Name (release)"]
        J --> K{"Required macros set,<br/>required blocks in the fit report,<br/>setup slack >= 0 on every clock?"}
        K -- "no" --> K1["Fail: nothing to deploy"]
        K -- "yes" --> L["build/output_files/rev.rbf,<br/>rev.sta.summary, q_staged.log"]
    end

    subgraph DEPLOY["scripts/deploy.py"]
        L --> M{"Log shows this build<br/>finished and met timing?"}
        M -- "no" --> M1["Refuse: never copy a stale .rbf"]
        M -- "yes" --> N["Next name Name_NNNNNNNN.rbf,<br/>numbered from 30000001"]
        N --> O["Copy to /media/fat/_Arcade/cores,<br/>append the machine-wide deploy log"]
        O --> P["validate_mra.py, then copy the .mra files"]
    end

    P --> Q["On the board: launch through menu.rbf only when asked,<br/>native screenshots, probe lines prefixed core/build/set"]
    Q --> R{"Plays correctly?"}
    R -- "no" --> S["Back to a bench: MAME capture or trace,<br/>state dump loaded into the simulator"]
    S --> D
    R -- "yes" --> T{"Release?"}
    T -- "not yet" --> E

    subgraph RELEASE["docs/RELEASE_PROCESS.md"]
        T -- "yes" --> U["Staged build of the release revision Name"]
        U --> V["Copy to releases/Arcade-Name_YYYYMMDD.rbf,<br/>git add -f"]
        V --> W["validate_mra.py strict, README current,<br/>squash develop onto master when the user asks"]
    end
```

The prefix rule: the `.mra` names the core without `Arcade-`, the file on the device follows it
(`Name_NNNNNNNN.rbf`), and only the released bitstream keeps the prefix, which the README's
install step tells the user to drop.
