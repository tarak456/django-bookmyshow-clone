"""
Custom template filters for the movies app.

Security note: all output that goes into HTML attributes is escaped via
Django's format_html only after the video ID has been strictly validated
against a whitelist regex. No user-supplied string is ever inserted raw.
"""
import re
from django import template
from django.utils.html import format_html, conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()

# YouTube video IDs are exactly 11 chars: letters, digits, hyphen, underscore.
_YT_ID_RE = re.compile(r'^[\w\-]{11}$')

# Hard-coded fallback HTML — no user data, so mark_safe is appropriate.
_FALLBACK_HTML = mark_safe(
    '<div class="trailer-fallback">'
    '<i class="fas fa-film fa-3x mb-3"></i>'
    '<p class="mb-0">Trailer not available</p>'
    '</div>'
)


def _safe_youtube_id(video_id):
    """
    Returns video_id only if it matches the strict YouTube ID pattern.
    This is the XSS gate — nothing else reaches the template.
    """
    if video_id and _YT_ID_RE.match(str(video_id)):
        return video_id
    return None


@register.filter(is_safe=True)
def youtube_embed(movie):
    """
    Usage in templates:
        {% load movie_tags %}
        {{ movie|youtube_embed }}

    Renders a privacy-enhanced, lazy-loaded YouTube iframe.
    Falls back to a styled placeholder when no trailer is available.

    Security:
    - The model validator (validate_youtube_url) blocks bad URLs at save time.
    - This filter re-validates the video ID via a strict regex before any DOM
      output, so even a corrupted DB value cannot cause XSS.
    - Embed uses youtube-nocookie.com (no tracking cookies).
    - sandbox restricts iframe capabilities to the minimum needed.
    - loading="lazy" defers the network request until the iframe is in view.
    - format_html escapes all interpolated values.
    """
    video_id = _safe_youtube_id(getattr(movie, 'youtube_embed_id', None))

    if video_id:
        return format_html(
            '<div class="trailer-wrapper">'
            '<iframe'
            ' src="https://www.youtube-nocookie.com/embed/{vid}"'
            ' title="{title} \u2014 Official Trailer"'
            ' loading="lazy"'
            ' referrerpolicy="no-referrer-when-downgrade"'
            ' sandbox="allow-scripts allow-same-origin allow-presentation"'
            ' allow="picture-in-picture; fullscreen"'
            ' allowfullscreen'
            ' style="border:0;position:absolute;top:0;left:0;width:100%;height:100%;"'
            '></iframe>'
            '</div>',
            vid=video_id,
            title=conditional_escape(movie.name),
        )

    return _FALLBACK_HTML
