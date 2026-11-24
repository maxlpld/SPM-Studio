"""Display labels for internal keys, without changing serialized identifiers.

Use this only at a UI boundary. File names, paths, model IDs, formulae and
scientific data stay verbatim. Combo boxes retain their original keys as data.
"""
from __future__ import annotations

LABELS = {
    'light_studio': 'Studio Light', 'dark_studio': 'Studio Dark',
    'Results_logs': 'Logs', 'results_logs': 'Logs',
    'auto': 'Automatic', 'file_search': 'File search',
    'tools_only': 'Local tools', 'custom_cloud': 'Custom cloud',
    'custom_local': 'Custom local', 'lmstudio': 'LM Studio',
    'openai': 'OpenAI', 'openrouter': 'OpenRouter', 'ollama': 'Ollama',
    'anthropic': 'Anthropic', 'gemini': 'Gemini', 'mistral': 'Mistral',
    'zotero': 'Zotero', 'confirmed_conclusion': 'Confirmed conclusion',
    'not_applicable': 'Not applicable', 'canceled': 'Cancelled',
    'cpd_histogram': 'CPD histogram', 'kpfm_edge': 'KPFM edge',
}
ACRONYMS = {'roi','cpd','spm','afm','stm','kpfm','fsrs','pdf','csv','json',
            'api','ssh','ui','dpi','fft','si','id','rmse','rms','fwhm'}


def ui_label(value: object) -> str:
    """Return a concise label for a declared key or already readable label."""
    text = str(value)
    if text in LABELS:
        return LABELS[text]
    words = text.replace('_', ' ').strip()
    if '_' in text:
        words = ' '.join(word.upper() if word.lower() in ACRONYMS else word for word in words.split())
    return words[:1].upper() + words[1:]


def add_key_items(combo, values) -> None:
    """Add readable Qt combo labels with lossless values in item data."""
    for value in values:
        combo.addItem(ui_label(value), value)


def combo_key(combo):
    """Read an item key; editable or legacy plain-text combos use their text."""
    value = combo.currentData()
    return combo.currentText() if value is None else value


def set_combo_key(combo, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
    else:
        combo.setCurrentText(str(value))
