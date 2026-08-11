# Secret Agenda Evidence Format Language

V1 is a deterministic template language for importing evidence formats Secret Agenda does not control.

The mental model is:

```text
copy a real card example
replace changing pieces with [fields]
preview the parse
ingest only after it looks right
```

## Basic Example

Input:

```text
-- 1 -- Smith 25
https://example.com/article
Artificial intelligence allows betting platforms to personalize offers.

-- 2 -- Jones 24
Federal regulation remains fragmented.
```

Grammar:

```text
-- [card] -- [author]
[link:url]?
[content]+
```

Preview:

```bash
./run.sh format-preview input.txt grammar.sa
```

JSON preview:

```bash
./run.sh format-preview input.txt grammar.sa --json
```

## Supported V1 Syntax

Fields:

```text
[card]
[author]
[title]
[link:url]
[content]
[custom_field]
```

Quantifiers:

```text
[field]?     optional
[field]*     zero or more
[field]+     one or more
```

Ignore fields:

```text
[_]?
```

Built-in types:

```text
text
line
block
url
number
date
```

Directives:

```text
@fuzzy 0.85

@defaults {
owner: opponent
side: aff
}
```

Alternatives:

```text
-- [card] -- [author] | Card [card]: [author]
[content]+
```

Escaped literal characters:

```text
-- [card] \| [author]
```

Comments:

```text
# opponent packet format
// alternate comment style
-- [card] -- [author]
[content]+
```

Local fuzzy overrides:

```text
-- [card] -- [author]~0.90
[content]+
```

## Parser Guarantees

- `[card]` is treated as a structural boundary.
- `[content]+` will not consume the next high-confidence card boundary.
- Literal matching tries exact, then normalized, then fuzzy matching.
- Typed validators beat fuzzy guesses, so `[link:url]` prefers real URLs.
- Low-confidence fuzzy structure is reported through diagnostics instead of silently trusted.
- The grammar engine only sees normalized text blocks. DOCX extraction stays separate.

## Not In V1 Yet

These are intentionally deferred:

```text
(...)
@card {}
@section {}
@document {}
AI-assisted grammar generation
```
