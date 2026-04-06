from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Look up a dictionary value by variable key."""
    if isinstance(dictionary, dict):
        return dictionary.get(key, 'no_data')
    return 'no_data'


@register.filter
def judgment_label(value):
    """Convert judgment code to human-readable label."""
    labels = {
        'support': 'Supported',
        'partial_support': 'Partially Supported',
        'not_support': 'Omitted',
        'no_data': 'No Data',
    }
    return labels.get(value, value)
