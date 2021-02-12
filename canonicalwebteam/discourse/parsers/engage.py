# Standard library
import os

# Packages
import dateutil.parser
import humanize
from bs4 import BeautifulSoup

# Local
from canonicalwebteam.discourse.exceptions import (
    PathNotFoundError,
)
from canonicalwebteam.discourse.parsers.base_parser import BaseParser


class EngageParser(BaseParser):
    """
    Parser exclusively for Engage pages
    """

    def parse(self):
        """
        Get the index topic and split it into:
        - index document content
        - URL map
        And set those as properties on this object
        """
        index_topic = self.api.get_topic(self.index_topic_id)
        raw_index_soup = BeautifulSoup(
            index_topic["post_stream"]["posts"][0]["cooked"],
            features="html.parser",
        )

        # Parse URL
        self.url_map, self.warnings = self._parse_url_map(
            raw_index_soup, self.url_prefix, self.index_topic_id, "Metadata"
        )

        engage_metadata, engage_errors = self._parse_engage_metadata(
            raw_index_soup, "Metadata"
        )
        self.metadata = engage_metadata
        self.engage_page_errors = engage_errors

        takeovers_metadata, takeovers_errors = self._parse_engage_metadata(
            raw_index_soup, "Takeovers"
        )
        self.takeovers = takeovers_metadata
        self.takeovers_errors = takeovers_errors

        if index_topic["id"] != self.index_topic_id:
            # Get body and navigation HTML
            self.index_document = self.parse_topic(index_topic)

    def parse_topic(self, topic):
        """
        Parse a topic object of Engage pages category from the Discourse API
        and return document data:
        - title: The title of the engage page
        - body_html: The HTML content of the initial topic post
            (with some post-processing)
        - updated: A human-readable date, relative to now
            (e.g. "3 days ago")
        - topic_path: relative path of the topic
        """

        updated_datetime = dateutil.parser.parse(
            topic["post_stream"]["posts"][0]["updated_at"]
        )

        topic_path = f"/t/{topic['slug']}/{topic['id']}"

        topic_soup = BeautifulSoup(
            topic["post_stream"]["posts"][0]["cooked"], features="html.parser"
        )

        self.current_topic = {}
        content = []
        warnings = []
        metadata = []

        for row in topic_soup.contents[0]("tr"):
            metadata.append([cell.text for cell in row("td")])

        if metadata:
            metadata.pop(0)
            self.current_topic.update(metadata)
            content = topic_soup.contents
            # Remove takeover metadata table
            content.pop(0)
        else:
            warnings.append("Metadata could not be parsed correctly")

        # Find URL in order to find tags of current topic
        current_topic_path = next(
            path for path, id in self.url_map.items() if id == topic["id"]
        )
        self.current_topic_metadata = next(
            (
                item
                for item in self.metadata
                if item["path"] == current_topic_path
            ),
        )

        # Combine metadata from index with individual pages
        self.current_topic_metadata.update(self.current_topic)

        # Expose related topics for thank-you pages
        # This will make it available for the instance
        # rather than the view
        current_topic_related = self._parse_related(
            self.current_topic_metadata["tags"]
        )

        return {
            "title": topic["title"],
            "metadata": self.current_topic_metadata,
            "body_html": content,
            "updated": humanize.naturaltime(
                updated_datetime.replace(tzinfo=None)
            ),
            "related": current_topic_related,
            "topic_path": topic_path,
        }

    def resolve_path(self, relative_path):
        """
        Given a path to a Discourse topic, and a mapping of
        URLs to IDs and IDs to URLs, resolve the path to a topic ID

        A PathNotFoundError will be raised if the path is not recognised.
        """

        full_path = os.path.join(self.url_prefix, relative_path.lstrip("/"))

        if full_path in self.url_map:
            topic_id = self.url_map[full_path]
        else:
            raise PathNotFoundError(relative_path)

        return topic_id

    def get_topic(self, topic_id):
        """
        Receives a single topic_id and
        @return the content of the topic
        """
        index_topic = self.api.get_topic(topic_id)
        return self.parse_topic(index_topic)

    def _parse_related(self, tags):
        """
        Filter index topics by tag
        This provides a list of "Related engage pages"
        """
        index_list = [item for item in self.metadata if item["tags"] in tags]
        return index_list

    def _parse_engage_metadata(self, index_soup, section_name):
        """
        Given the HTML soup of an index topic
        extract the metadata from the name designated
        by section_name

        This section_name section should contain a table
        (extra markup around this table doesn't matter)
        e.g.:

        <h1>Metadata</h1>
        <details>
            <summary>Mapping table</summary>
            <table>
            <tr><th>Column 1</th><th>Column 2</th></tr>
            <tr>
                <td>data 1</td>
                <td>data 2</td>
            </tr>
            <tr>
                <td>data 3</td>
                <td>data 4</td>
            </tr>
            </table>
        </details>

        This will typically be generated in Discourse from Markdown similar to
        the following:

        # Redirects

        [details=Mapping table]
        | Column 1| Column 2|
        | -- | -- |
        | data 1 | data 2 |
        | data 3 | data 4 |

        The function will return a list of dictionaries of this format:
        [
            {"column-1": "data 1", "column-2": "data 2"},
            {"column-1": "data 3", "column-2": "data 4"},
        ]
        """
        metadata_soup = self._get_section(index_soup, section_name)

        topics_metadata = []
        metadata_errors = []
        if metadata_soup:
            titles = [
                title_soup.text.lower().replace(" ", "_").replace("-", "_")
                for title_soup in metadata_soup.select("th")
            ]
            for row in metadata_soup.select("tr:has(td)"):
                row_dict = {}
                for index, value in enumerate(row.select("td")):
                    if value.find("a"):

                        row_dict["topic_name"] = value.find("a").text

                        # Only engage pages need a link
                        if value.findAll("a", href=True):
                            if value.find("a")["href"] == value.find("a").text:
                                value.contents[0] = value.find("a").text

                        else:
                            metadata_errors.append(
                                f"Warning: row {index} \"{row_dict['topic_name']}\"\
                                {titles[index]} contains an error. This Engage\
                                 page has been skipped."
                            )
                            row_dict = None
                            break

                    # Missing path will cause the engage item in index to not
                    # link to the corresponding page
                    # Missing type will cause resource_name to be empty in
                    # thank-you pages
                    # This error does not need breaking, because it does not
                    # break the page
                    if (
                        (titles[index] == "path") or (titles[index] == "type")
                    ) and ((value.text == "") or (value.text is None)):
                        metadata_errors.append(
                            f"Warning: row {index} \"{row_dict['topic_name']}\"\
                            {titles[index]} is missing. This Engage page has \
                            been skipped."
                        )

                    row_dict[titles[index]] = "".join(
                        str(content) for content in value.contents
                    )
                if row_dict:
                    topics_metadata.append(row_dict)

        return topics_metadata, metadata_errors
