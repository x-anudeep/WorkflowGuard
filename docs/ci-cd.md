# CI/CD

Install the CLI with:

```bash
pip install -e packages/workflow-core
```

Useful commands:

```bash
workflowguard validate <file>
workflowguard evaluate <file> --prompt "..."
workflowguard test <file> --json
workflowguard cost <file> --json
workflowguard check <file> --json
workflowguard report <file> --format markdown
workflowguard compare <fileA> <fileB> --json
```

`check` executes deterministic validation, evaluation, test generation/run, cost estimation, and quality gates. Exit code `0` means pass, `1` means parsed but gate/validation/test failure, and `2` means read/parse error. `.github/workflows/workflowguard.yml` provides a PR example and does not require paid AI by default.
