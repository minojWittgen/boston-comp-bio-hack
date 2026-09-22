# Capturing `usage` fairly across A, B and C

## A and B (your scaffold)

Wrap every LLM call and sum the provider's `usage` object. Do not estimate from
string length. One accumulator per run:

```python
class Usage:
    def __init__(self, model): self.model=model; self.i=self.o=self.c=self.llm=self.tools=self.net=0; self.t0=time.time()
    def add_llm(self, resp):  # Anthropic: resp.usage.{input_tokens,output_tokens,cache_read_input_tokens}
        u = resp.usage; self.llm += 1
        self.i += u.input_tokens + getattr(u, "cache_read_input_tokens", 0)
        self.c += getattr(u, "cache_read_input_tokens", 0)
        self.o += u.output_tokens
    def add_tool(self): self.tools += 1
    def dump(self): return dict(model=self.model, input_tokens=self.i, cache_read_tokens=self.c,
                                output_tokens=self.o, llm_calls=self.llm, tool_calls=self.tools,
                                wall_clock_s=round(time.time()-self.t0,1), network_calls=self.net)
```

Because B is A plus criterion tracking, B's system prompt is longer and it makes
more follow-up calls. That is the cost being measured — do not trim B's prompt to
make the numbers look better; report `b_over_a_token_ratio` as is.

## C (external comparator, e.g. Biomni)

Drive C through a thin adapter so it gets the **same case prompt** (claim +
instruction + the fixture files as attachments/paths) and its answer is mapped
into `agent_output.schema.json`.

Token capture options, in order of preference:

1. C exposes a callback/log of LLM usage → sum it exactly as above.
2. C lets you inject the LLM client → wrap it with the accumulator.
3. Neither → put a logging proxy in front of the API endpoint (`base_url`) and
   sum `usage` from the proxied responses.

Never fall back to counting tokens in C's printed transcript; that misses system
prompts and tool results, which is usually most of the bill.

Things to record for C that don't apply to A/B:

- `network_calls`: C will typically call PubMed / Open Targets / UniProt live.
  Count them (proxy logs or C's own tool log). If > 0, C has seen evidence that
  eval mode deliberately hides from A/B, and its correctness rows must be
  labelled "not comparable, saw live literature" in the write-up.
- `model`: if C runs a different model than A/B, all C numbers are "different
  stack" numbers. Say so once, up front, and don't argue from them.
- Whether C had read access to `held_out/`. It must not.

## What to put in the write-up

One table, four columns: configuration · pass rate (all rows) · median tokens ·
tokens per pass. Then one sentence per configuration. The claim you can support
is "B costs X× A's tokens and Y× C's, and converts them into Z× the pass rate";
the claim you cannot support is "B is cheaper than Biomni", unless model and
tool access were matched.
