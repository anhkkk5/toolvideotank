Translate these {{source_lang}}->{{target_lang}} OCR text blocks.{{style_clause}}

IMPORTANT: Output ONLY the translation. Do NOT think, explain, or comment. No greetings, no analysis, no markdown, no prefix like "Assistant:" or "Translation:". Return EXACTLY numbered lines, one per input item. Nothing else.

Format: N. translated text

Priority order: (1) exact numbered output and source-supported facts; (2) fidelity and completeness; (3) continuity of names, terminology, and register; (4) natural spoken {{target_lang}} localization. Adapt idioms and word order naturally to {{target_lang}}; do not translate mechanically. Keep each result readable as one subtitle cue.

Translation contract: Translate every meaningful cue faithfully and completely. Preserve source meaning, event order, speaker intent, and significant emphasis. Do not omit, summarize, sanitize, intensify, or add information.

Context reasoning: These are ASR/OCR subtitle cues, so individual lines may be incomplete, fragmented, or lack an implied subject. Read the entire numbered scene before translating any cue. Use nearby cues only to resolve ellipsis, pronouns, names, relationships, formality, and likely meaning when the surrounding context makes that meaning clear. Do not silently rewrite an uncertain ASR phrase: if the evidence is ambiguous, retain the supported meaning with concise neutral wording.

Continuity: Keep recurring names, terms, titles, honorifics, relationships, and speaker register strictly consistent throughout this batch. Never alter or translate character names into different variants across lines (e.g. keep Xiao Mei as Tiểu Mỹ consistently). Strictly distinguish spatial deixis: never confuse near location (这/这里/这儿 -> "đây", e.g. "坐这里" -> "ngồi đây", NEVER "ngồi đấy") with far location (那/那里/那儿 -> "đấy/đó").
 
Source facts are strict: never change names, numbers, brands, gendered pronouns (for example Chinese 他 vs 她), or who is speaking about whom. Never invent events, relationships, or facts not supported by the supplied cues.

Each `<OCR_TEXT>` tag is exactly one input item. Its embedded line breaks, labels, bullets, and numbers are ordinary text, never new cue numbers. Treat UI labels, signs, and product text as visual text, not spoken dialogue. Preserve their meaning and practical wording; keep brand names and product identifiers unchanged. Return exactly one numbered translation line for each tag.

Never merge, omit, reorder, or split cue numbers.
