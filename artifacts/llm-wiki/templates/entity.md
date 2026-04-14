---
type: entity
subtype: tool           # tool | person | project | org | service
name: <Name>
status: active          # active | deprecated | archived
confidence: CONFIRMED   # CONFIRMED | INFERRED | AMBIGUOUS
hub: false
tags: [tag1, tag2]
related:
  - concepts/some-concept.md
  - decisions/some-decision.md
updated: YYYY-MM-DD
---

# <Name>

## What it is
One-paragraph description of what this entity is.

## How we use it
Specific to our deployment: location, config, integration points.

## Key properties
- Property one
- Property two
- Property three

## Connections
- **Powers:** [[linked-page]] — brief description
- **Deployed alongside:** [[other-entity]]
- **Alternative to:** Other Option (INFERRED: reason)
- **Limitation:** Known constraint or caveat

## Open questions
- [ ] Unresolved question about this entity
