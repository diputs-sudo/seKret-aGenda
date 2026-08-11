# Debate Side Engine

The side engine keeps three concepts separate:

```text
owner != side != stance
```

## Fields

`owner` answers who supplied the evidence:

```text
us
opponent
shared
unknown
```

`side` answers which formal side the evidence is assigned to for a round:

```text
affirmative
negative
unknown
```

`stance` answers what the card does argumentatively:

```text
supports
opposes
qualifies
turns
indicts
non_unique
mitigates
impact
unknown
```

These can be set during `.sa` ingestion through defaults:

```text
@defaults {
owner: opponent
side: unknown
packet: opponent-backfile
}
```

## Round Context

Round context changes per round without rewriting the database:

```bash
OUR_SIDE=negative OPPONENT_SIDE=affirmative \
  ./run.sh side "opponent says AI sports betting increases addiction"
```

## Query Control Language

The debate query parser consumes control words before retrieval.

```text
opponent says AI betting increases addiction
```

becomes:

```text
intent: answer
semantic query: AI betting increases addiction
```

So `opponent` and `says` are not treated as retrieval concepts.

Supported command prefixes:

```text
answer>  opponent claim
their>   find opponent evidence
compare> both lanes
turn>    prefer turns
indict>  prefer warrant/source/mechanism attacks
search>  neutral retrieval
```

## Output Shape

The engine produces two lanes:

```text
OUR ANSWERS
cards we can read or use as answers

OPPONENT EVIDENCE
cards that model, qualify, or expose their position
```

The retriever still finds broadly relevant evidence. The side engine decides how useful each card is for this speaker, intent, owner, side, and stance.
