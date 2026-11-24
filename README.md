# pii-screen

If you send customer messages, job notes or call summaries to a hosted AI model, you are probably also sending phone numbers, emails, street addresses and names.
pii-screen is a small Python library and command line tool that sits in front of that call and takes those details out first.

- **For whom:** a business or developer who wants to use a third party model on real customer text without handing over contact details.
- **What you get:** the model sees `[[NAME_1]]` and `[[PHONE_1]]` instead of the real values, and its reply comes back with the real values put back in. Or the details are masked one way, or the call is stopped outright.
- **How you know it works:** it ships a labelled test set and reports its own hit and miss rates, including a list of every case it gets wrong.
- **What it is not:** it is pattern matching, not a compliance product. It has only been run on synthetic text and an offline mock model. See [Limitations](#limitations).

## What you will see

Real output from `python demo/run_demo.py` (offline, no key, synthetic message). Full capture in [`demo/output.txt`](demo/output.txt).

```
Alex Sample called from (555) 555-0142 about the leak at 123 Example Street. Send the quote to alex.sample@example.com. Alex is home after 4.

The model received:
  [[NAME_1]] called from [[PHONE_1]] about the leak at [[ADDRESS_1]]. Send the quote to [[EMAIL_1]]. [[NAME_2]] is home after 4.
The model replied:
  Draft reply: Hello [[NAME_1]], thanks for your message (19 words). We can send someone to [[ADDRESS_1]]. We will confirm the time using [[PHONE_1]].
The caller gets back, placeholders restored:
  Draft reply: Hello Alex Sample, thanks for your message (19 words). We can send someone to 123 Example Street. We will confirm the time using (555) 555-0142.

BlockedError: blocked: 5 finding(s) of kind ADDRESS, EMAIL, NAME, PHONE
calls that reached the model: 0
```

"The model" here is a mock that runs in the same process. Nothing in this repo calls a real model service.

## What it does

- **Detects** four kinds of detail: phone numbers, email addresses, street addresses, and names from a roster you supply (one name per line). Names are never guessed; only roster names are looked for.
- **Three modes**
  - `block`: if anything is found, nothing is passed on. The CLI exits with code 2.
  - `redact`: each finding becomes `[PHONE]`, `[EMAIL]`, `[ADDRESS]` or `[NAME]`. One way.
  - `tokenise`: each finding becomes a numbered placeholder such as `[[NAME_1]]`. The same string always gets the same placeholder, and a vault kept on your side maps them back, so the model's reply can be restored.
- **Measures itself**: ships a labelled synthetic corpus (110 messages, 177 labelled spans) and reports precision and recall per kind.
- Library and CLI. Standard library only, no dependencies, no network calls.

```python
from pii_screen import Roster, Screener, guarded_call

screener = Screener(Roster.from_file("corpus/roster.txt"))

result = screener.screen("Call Alex Sample on 555-555-0142", mode="tokenise")
result.text                        # 'Call [[NAME_1]] on [[PHONE_1]]'
result.vault.restore(result.text)  # 'Call Alex Sample on 555-555-0142'

# Or wrap the model call. send() is any function you write that takes a
# string and returns the reply. It only ever sees the screened text.
reply = guarded_call(screener, message, send=my_model_client, mode="tokenise")
```

## Architecture

```mermaid
flowchart LR
    T[Outgoing text] --> D
    R[Roster file] --> D
    subgraph screen[pii-screen]
        D[Detectors: email, phone, address, roster names] --> O[Merge overlaps]
        O --> M{Mode}
        M -->|block| B[Stop. Nothing sent]
        M -->|redact| X["[KIND] labels"]
        M -->|tokenise| K["[[KIND_n]] placeholders"]
        K <--> V[(Vault, kept local)]
    end
    X --> P[Third party model]
    K --> P
    P --> A[Reply]
    A --> S[Restore from vault]
    V --> S
    S --> U[Caller]
    C[Labelled corpus] --> E[Evaluator]
    D --> E
    E --> Q[Precision and recall report]
```

| Path | Purpose |
| --- | --- |
| `pii_screen/detectors.py` | Patterns for email, phone and address; roster name matcher; overlap merging |
| `pii_screen/screen.py` | `Screener`, the three modes, `Vault`, `guarded_call` |
| `pii_screen/evaluate.py` | Scores the screen against the corpus |
| `pii_screen/cli.py` | `screen`, `restore`, `eval` commands |
| `pii_screen/mock_model.py` | Offline stand-in for a model, used by the tests and the demo |
| `corpus/` | `build_corpus.py` (labels written inline), the generated `corpus.jsonl`, and `roster.txt` |

## Run it

Needs Python 3.10 or newer. Nothing to install.

```bash
echo "Call Alex Sample on 555-555-0142" | python -m pii_screen screen --roster corpus/roster.txt --vault vault.json
python -m pii_screen eval --errors
python demo/run_demo.py
```

More CLI examples (`message.txt` and `reply.txt` are your own files):

```bash
python -m pii_screen screen message.txt --mode redact
python -m pii_screen screen message.txt --mode block          # exit code 2 if anything is found
python -m pii_screen restore reply.txt --vault vault.json     # swap placeholders back
python -m pii_screen eval --full-names-only                   # stricter name matching
```

`pip install -e .` also gives you a `pii-screen` command. Defaults for mode and roster can come from the environment, see `.env.example`. Findings are logged to stderr by kind and position only, never by value.

## Tests

```bash
python -m unittest discover -s tests -v
```

45 tests cover each detector, the three modes, vault round trips, the guarded model call, the scoring maths, the CLI, and a check that the shipped corpus matches its builder. CI (`.github/workflows/ci.yml`) runs the same on Python 3.10 and 3.12, then rebuilds the corpus to check it is in sync, and runs the eval and the demo.

## Demo

`python demo/run_demo.py` runs offline with no key. It screens one synthetic message in all three modes, sends the tokenised version through the mock model and restores the reply, shows block mode stopping the call, and prints the precision and recall report with every miss and false positive. The excerpt under [What you will see](#what-you-will-see) is copied from its output; the full capture is in [`demo/output.txt`](demo/output.txt).

## Precision and recall

Measured on the shipped corpus with the shipped roster, default settings:

```
Exact span match (kind, start and end all equal)
kind       gold  pred    tp    fp    fn  precision  recall     f1
EMAIL        35    34    34     0     1      1.000   0.971  0.986
PHONE        49    48    45     3     4      0.938   0.918  0.928
ADDRESS      38    36    35     1     3      0.972   0.921  0.946
NAME         55    57    50     7     5      0.877   0.909  0.893
ALL         177   175   164    11    13      0.937   0.927  0.932
```

With `--full-names-only`, name precision rises to 1.000 and name recall falls to 0.782, because a first name on its own is no longer matched.

Read these numbers for what they are. The corpus has 70 template generated messages and 40 hand written ones. The generated messages use formats the patterns were written for, and the screen gets all of them. Every error comes from the hand written set, which was built on purpose to include things the screen misses (a spelled out email, a phone number with odd spacing, a lowercase street address, a misspelled name), things it flags wrongly (a part number that looks like a phone number, "Sample photos" when a roster surname is "Sample"), and clean messages. So the figures show where the edges are. They are not a forecast of accuracy on your own traffic. Label a sample of your own messages in the same JSONL format and run `eval --corpus yours.jsonl --roster yours.txt` to find out.

## Where this pattern comes from

The idea is drawn from day to day work at two small service companies, where customer messages, job notes and call summaries are handed to hosted models for drafting and summarising. This repo is a standalone version written to show the approach. The code here has only been run on the synthetic corpus and the mock model.

## Limitations

- **Never run against a live model service.** `pii_screen/mock_model.py` is a canned reply generator in the same process. There is no client for any model provider in this repo; you pass your own `send` function to `guarded_call`. How a real model treats the placeholders (keeps them intact, rewrites them, drops them) is untested. A placeholder the model alters is not restored.
- **Only tested on synthetic text.** Every message, name and contact detail in the corpus is invented. No real customer traffic has been measured, and there are no speed or volume figures.
- **Pattern based.** Anything written in an unexpected form gets through: "alex at example dot com", digits spelled as words, phone numbers with unusual spacing, lowercase street addresses, addresses with no house number first.
- **Names come only from the roster.** A person who is not on the roster is not detected at all, and the corpus does not label such names. Misspellings and initials are only partly caught.
- **Single name parts cause false positives** when a roster name is also an ordinary capitalised word. Use `--full-names-only` (or `Roster(..., match_parts=False)`) to trade recall for precision.
- **North American formats only** for phones and street addresses. No international numbers, no non English address styles.
- **Only four kinds of detail.** No account numbers, government ids, dates of birth, payment cards or free text that identifies someone indirectly.
- **No coreference.** "Alex Sample" and a later "Alex" get different placeholders, so the model cannot tell they are one person.
- **Exact string keys.** The same phone number in two formats gets two placeholders.
- **Literal placeholders in the input.** A new placeholder never reuses one that already appears in the text being screened, but if a text contains a literal `[[NAME_1]]` and a vault reused from an earlier message already holds that key, restore will swap it.
- **The vault is sensitive.** It holds the real values in plain JSON. Keep it local, do not commit it, and delete it when the exchange is over.
- **Not a compliance tool.** It lowers the chance of sending personal details by accident. It does not guarantee that none are sent, and a blocked or clean result is not proof that a text is free of personal data.

License: MIT, see the LICENSE file.
