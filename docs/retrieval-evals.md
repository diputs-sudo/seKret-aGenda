# Retrieval Evals

These queries are the first quality gate for retrieval.

The point is not to prove the system is perfect. The point is to catch obvious retrieval failures before generation turns them into bad speeches.

## Eval Set

### AI Cautious

Query:

```text
AI cautious
```

Expected:

- Tucker 20

Reject:

- unrelated AI agriculture cards
- unrelated regulation cards

### Automation Escalation

Query:

```text
automation escalation
```

Expected:

- Cox 21
- Goldfarb 22
- Tucker 20

Reject:

- Shapiro 26
- unrelated India nuclear war cards
- unrelated housing or agriculture cards

### Quantum Encryption

Query:

```text
quantum encryption
```

Expected:

- Hunt 26
- Warburton 25

Reject:

- non-quantum cards

### Capitalism

Query:

```text
capitalism
```

Expected:

- capitalism / critique cards, if present in the corpus

Reject:

- unrelated topic cards

### Housing Supply

Query:

```text
housing supply
```

Expected:

- housing cards about supply, rents, development, or ownership

Reject:

- unrelated technology or security cards

### Author Lookup

Query:

```text
Tucker
```

Expected:

- Tucker 20

Reject:

- cards where Tucker appears only in unrelated body text, if any

