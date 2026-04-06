"""Shared utility functions for analysis app."""


def classify_leaning(
    left: float,
    center: float,
    right: float,
    margin_threshold: float = 0.1,
) -> str:
    """Classify political leaning with margin-based center detection.

    If the gap between the top two probabilities is below margin_threshold,
    the content is classified as "center" (model uncertain = balanced content).
    """
    probs = {'left': left, 'center': center, 'right': right}
    sorted_probs = sorted(probs.items(), key=lambda x: -x[1])
    top_class, top_prob = sorted_probs[0]
    _, second_prob = sorted_probs[1]

    if top_prob - second_prob < margin_threshold:
        return 'center'
    return top_class
