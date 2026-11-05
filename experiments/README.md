# GPT-6 direct API validation

`validate_gpt6.py` calls `https://api.openai.com/v1/responses` directly with
`gpt-6-astra`, strict JSON Schema, low reasoning effort, and `store: false`.
It requires `OPENAI_API_KEY` in the process environment. No Gateway credential
or Gateway fallback is used. Never put the key in tracked source files.

Run from prototype-1.1 after setting the key in your local terminal:

```sh
/opt/anaconda3/bin/python experiments/validate_gpt6.py
```

The eight English cases check spelling correction, ingredient roles, hard and
soft constraints, unit conversion, conflicts, planning, unrelated requests,
and negation. Checks are limited smoke checks, not a full accuracy benchmark.
Results go to `verification/gpt6-direct-intent-validation.json`, including the
requested and returned model, prompt version, schema, output, usage, and timing.
The earlier Gateway failure remains in its separate historical result file.

Current status: local response parsing checks passed; live direct validation
has not run because OPENAI_API_KEY was absent from the executing environment.
The existing web page's Jev integration has not been replaced by this experiment.
