# Standard library
import re

# Packages
import dateutil.parser
import humanize
from bs4 import BeautifulSoup
from jinja2 import Template

# Local
from canonicalwebteam.discourse_docs.exceptions import PathNotFoundError


TOPIC_URL_MATCH = re.compile(
    r"(?:/t)?(?:/(?P<slug>[^/]+))?/(?P<topic_id>\d+)(?:/\d+)?"
)


def resolve_path(path):
    """
    Given a path to a Discourse topic, resolve the path to a topic ID

    A PathNotFoundError will be raised if the path is not recognised.

    A RedirectFoundError will be raised if the topic should be
    accessed at a different URL path.
    """

    topic_match = TOPIC_URL_MATCH.match(path)

    if not topic_match:
        raise PathNotFoundError(path)

    topic_id = int(topic_match.groupdict()["topic_id"])

    return topic_id


def parse_index(topic):
    """
    Parse the index document topic to parse out:
    - The body HTML
    - The navigation markup

    Set all as properties on the object
    """

    index = parse_topic(topic)
    index_soup = BeautifulSoup(index["body_html"], features="html.parser")

    # Get the nav
    index["body_html"] = str(
        get_preamble(index_soup, break_on_title="Content")
    )

    # Parse navigation
    index["navigation"] = parse_navigation(index_soup)

    return index


def parse_topic(topic):
    """
    Parse a topic object from the Discourse API
    and return document data:
    - title: The title
    - body_html: The HTML content of the initial topic post
                    (with some post-processing)
    - updated: A human-readable date, relative to now
                (e.g. "3 days ago")
    - forum_link: The link to the original forum post
    """

    updated_datetime = dateutil.parser.parse(
        topic["post_stream"]["posts"][0]["updated_at"]
    )

    return {
        "title": topic["title"],
        "body_html": process_topic_html(
            topic["post_stream"]["posts"][0]["cooked"]
        ),
        "updated": humanize.naturaltime(updated_datetime.replace(tzinfo=None)),
        "topic_path": f"/t/{topic['slug']}/{topic['id']}",
    }


def parse_navigation(index_soup):
    """
    Given the HTML soup of a index topic
    extract the "navigation" section
    """

    nav_soup = get_section(index_soup, "Content")
    nav_html = "Navigation missing"

    if nav_soup:
        nav_html = str(nav_soup)

    return nav_html


def process_topic_html(html):
    """
    Given topic HTML, apply post-process steps
    """

    soup = BeautifulSoup(html, features="html.parser")
    soup = replace_notifications(soup)
    soup = replace_notes_to_editors(soup)

    return str(soup)


def replace_notes_to_editors(soup):
    """
    Given HTML soup, remove 'NOTE TO EDITORS' sections.

    We expect these sections to be of the HTML format:

    <aside class="quote no-group">
      <blockquote>
        <p>
          <img title=":construction:" class="emoji" ...>
          <strong>NOTE TO EDITORS</strong>
          <img title=":construction:" class="emoji" ...>
        </p>
        <p> ... </p>
      </blockquote>
    </aside>
    """

    notes_to_editors_text = soup.find_all(text="NOTE TO EDITORS")

    for text in notes_to_editors_text:
        # If this section is of the expected HTML format,
        # we should find the <aside> container 4 levels up from
        # the "NOTE TO EDITORS" text
        container = text.parent.parent.parent.parent

        if container.name == "aside" and "quote" in container.attrs["class"]:
            container.decompose()

    return soup


def replace_notifications(soup):
    """
    Given some BeautifulSoup of a document,
    replace blockquotes with the appropriate notification markup

    E.g.:

        <blockquote><p>ⓘ Content</p></blockquote>
    
    Becomes:
        <div class="p-notification">
            <div class="p-notification__response">
                <p class="u-no-padding--top u-no-margin--bottom">Content</p>
            </div>
        </div>
    """

    notification_html = (
        "<div class='{{ notification_class }}'>"
        "<div class='p-notification__response'>"
        "{{ contents | safe }}"
        "</div></div>"
    )

    notification_template = Template(notification_html)
    for note_string in soup.findAll(text=re.compile("ⓘ ")):
        first_paragraph = note_string.parent
        blockquote = first_paragraph.parent
        last_paragraph = blockquote.findChildren(recursive=False)[-1]

        if first_paragraph.name == "p" and blockquote.name == "blockquote":
            # Remove extra padding/margin
            first_paragraph.attrs["class"] = "u-no-padding--top"
            if last_paragraph.name == "p":
                if "class" in last_paragraph.attrs:
                    last_paragraph.attrs["class"] += " u-no-margin--bottom"
                else:
                    last_paragraph.attrs["class"] = "u-no-margin--bottom"

            # Remove control emoji
            notification_html = blockquote.encode_contents().decode("utf-8")
            notification_html = re.sub(
                r"^\n?<p([^>]*)>ⓘ +", r"<p\1>", notification_html
            )

            notification = notification_template.render(
                notification_class="p-notification", contents=notification_html
            )
            blockquote.replace_with(
                BeautifulSoup(notification, features="html.parser")
            )

    for warning in soup.findAll("img", title=":warning:"):
        first_paragraph = warning.parent
        blockquote = first_paragraph.parent
        last_paragraph = blockquote.findChildren(recursive=False)[-1]

        if first_paragraph.name == "p" and blockquote.name == "blockquote":
            warning.decompose()

            # Remove extra padding/margin
            first_paragraph.attrs["class"] = "u-no-padding--top"
            if last_paragraph.name == "p":
                if "class" in last_paragraph.attrs:
                    last_paragraph.attrs["class"] += " u-no-margin--bottom"
                else:
                    last_paragraph.attrs["class"] = "u-no-margin--bottom"

            # Strip leading space
            first_item = last_paragraph.contents[0]
            first_item.replace_with(first_item.lstrip(' '))

            notification = notification_template.render(
                notification_class="p-notification--caution",
                contents=blockquote.encode_contents().decode("utf-8"),
            )

            blockquote.replace_with(
                BeautifulSoup(notification, features="html.parser")
            )

    return soup


def get_preamble(soup, break_on_title):
    """
    Given a BeautifulSoup HTML document,
    separate out the HTML at the start, up to
    the heading defined in `break_on_title`,
    and return it as a BeautifulSoup object
    """

    heading = soup.find(re.compile("^h[1-6]$"), text=break_on_title)

    if not heading:
        return soup

    preamble_elements = heading.fetchPreviousSiblings()
    preamble_elements.reverse()
    preamble_html = "".join(map(str, preamble_elements))

    return BeautifulSoup(preamble_html, features="html.parser")


def get_section(soup, title_text):
    """
    Given some HTML soup and the text of a title within it,
    get the content between that title and the next title
    of the same level, and return it as another soup object.
    
    E.g. if `soup` contains is:

      <p>Pre</p>
      <h2>My heading</h2>
      <p>Content</p>
      <h2>Next heading</h2>

    and `title_text` is "My heading", then it will return:

    <p>Content</p>
    """

    heading = soup.find(re.compile("^h[1-6]$"), text=title_text)

    if not heading:
        return None

    heading_tag = heading.name

    section_html = "".join(map(str, heading.fetchNextSiblings()))
    section_soup = BeautifulSoup(section_html, features="html.parser")

    # If there's another heading of the same level
    # get the content before it
    next_heading = section_soup.find(heading_tag)
    if next_heading:
        section_elements = next_heading.fetchPreviousSiblings()
        section_elements.reverse()
        section_html = "".join(map(str, section_elements))
        section_soup = BeautifulSoup(section_html, features="html.parser")

    return section_soup