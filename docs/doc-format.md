# Document Format Notes

These notes describe the debate evidence document format that the parser should support.

## Core Terms

### AT

`AT` means **Answer To**.

Everything underneath an `AT:` heading is a response to one specific opponent argument.

Example:

```text
AT: Hyperwar
```

This means the cards below answer the opponent's Hyperwar argument.

The parser should not stop after finding one matching header. Arguments may repeat throughout the document, so retrieval should be able to surface cards from multiple matching sections.

### Argument Header

Sometimes a header will not include `AT:` and may simply say something like:

```text
Cap Good
```

In that case, the header itself is the argument, and the cards below support that argument.

### OV

`OV` means **Overview**.

An overview applies to an entire side, such as AFF or NEG, rather than only one narrow argument.

### Card Name

A card name is a quick label used to identify the full card.

It is usually the author's last name plus year.

Examples:

```text
Asenger '25
Smith '20
Tucker 20
```

Debaters use this label to refer to evidence quickly.

### Tag

The tag is a one-line summary of what the card proves.

Example:

```text
AI is risk-averse.
```

The tag is the claim being made with the evidence.

### Citation

The citation line appears below the tag.

It usually includes:

- Author name
- Qualifications
- Publication
- Date
- Article title
- Source URL
- Optional internal notes

Example:

```text
Tucker 20, Technology Editor @ Defense One. (Patrick, 4/29/20, "Artificial Intelligence Outperforms Human Intel Analysts In a Key Area", Defense One, https://www.defenseone.com/technology/2020/04/artificial-intelligence-outperforms-human-intel-analysts-one-key-area/165022/) // recut cpsof
```

### Card Text

The card text is the quoted evidence from the source.

Highlighted portions are the parts actually read in-round. The parser should preserve highlighted text separately from the full body if possible.

Bold and underline are emphasis only. They may be preserved, but they are less important than highlights.

## Typical Structure

```text
Argument header

Tag

Citation

Card text with highlighted read-round evidence

Remaining article text / context
```

Concrete example:

```text
AT: Hyperwar

AI is risk-averse.

Tucker 20, Technology Editor @ Defense One. (Patrick, 4/29/20, "Artificial Intelligence Outperforms Human Intel Analysts In a Key Area", Defense One, URL)

In the 1983 movie WarGames...
```

## Parser Requirements

The parser should preserve:

- Argument header, including whether it was explicitly marked `AT:`
- Tag
- Card name
- Citation
- Full card text
- Highlighted text
- Highlight colors, if available
- Formatting when useful, especially highlights

The parser should tolerate:

- Missing `AT:` prefixes
- Repeated arguments
- Slight formatting inconsistencies between documents
- Extra notes in citation lines
- Debate shorthand

## Topic Classification Notes

Some arguments are topical and relate directly to the debate topic.

Examples:

- Climate change
- Extinction
- AGI

Some arguments are non-topical and do not directly pertain to the topic.

Examples:

- Philosophy, such as Kant or Zizek
- Critiques of concepts, such as Capitalism or Orientalism
- Theory arguments that critique debate rules or norms and offer an interpretation

Responses should be able to mix topical and non-topical evidence when useful.

## Debate Shorthand

`Dedev` means economic development bad. It argues against economic development.

The AI should understand common debate shorthand, but the parser should store the original text rather than trying to rewrite it too aggressively.

## Draft JSON Shape

```json
{
  "argument": "AT: Hyperwar",
  "argument_type": "answer_to",
  "tag": "AI is risk-averse.",
  "card_name": "Tucker 20",
  "citation": "Tucker 20, Technology Editor @ Defense One. ...",
  "body": "In the 1983 movie WarGames...",
  "highlighted": [
    {
      "text": "more cautious than humans",
      "color": "unknown"
    }
  ],
  "formatting": {
    "bold": true,
    "underline": true
  }
}
```
