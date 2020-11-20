import flask
from requests.exceptions import HTTPError

from canonicalwebteam.discourse.exceptions import (
    PathNotFoundError,
    RedirectFoundError,
)


class Docs(object):
    """
    A Flask extension object to create a Blueprint
    to serve documentation pages, pulling the documentation content
    from Discourse.

    :param api: A DiscourseAPI for retrieving Discourse topics
    :param index_topic_id: ID of a forum topic containing nav & URL map
    :param category_id: Only show docs from topics in this forum category
    :param url_prefix: URL prefix for hosting under (Default: /docs)
    :param document_template: Path to a template for docs pages
                              (Default: docs/document.html)
    """

    def __init__(
        self,
        parser,
        document_template="docs/document.html",
        url_prefix="/docs",
        blueprint_name="docs",
    ):
        self.blueprint = flask.Blueprint(blueprint_name, __name__)
        self.url_prefix = url_prefix
        self.parser = parser
        category_id = self.parser.category_id

        @self.blueprint.route("/sitemap.txt")
        def sitemap_view():
            """
            Show a list of all URLs in the URL map
            """

            self.parser.parse()

            urls = []

            for key, value in self.parser.url_map.items():
                if type(key) is str:
                    urls.append(flask.request.host_url.strip("/") + key)

            return (
                "\n".join(urls),
                {"Content-Type": "text/plain; charset=utf-8"},
            )

        @self.blueprint.route("/sitemap.xml")
        def sitemap_xml():
            """
            Show a list of all URLs in the URL map
            """

            self.parser.parse()
            pages = []
            for key, value in self.parser.url_map.items():
                if type(key) is str:
                    try:
                        response = parser.api.get_topic(str(value))
                        last_updated = response["post_stream"]["posts"][0][
                            "updated_at"
                        ]
                    except Exception:
                        last_updated = None

                    pages.append(
                        {
                            "url": flask.request.host_url.strip("/") + key,
                            "last_updated": last_updated,
                        }
                    )

            from jinja2 import Template

            tm = Template(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
                "{% for page in pages %}"
                "<url>"
                "<loc>{{ page['url'] }}</loc>"
                "<changefreq>weekly</changefreq>"
                "<lastmod>{{ page['last_updated'] }}</lastmod>"
                "</url>"
                "{% endfor %}"
                "</urlset>"
            )
            xml_sitemap = tm.render(pages=pages)

            response = flask.make_response(xml_sitemap)
            response.headers["Content-Type"] = "application/xml"
            response.headers["Cache-Control"] = "public, max-age=43200"

            return response

        @self.blueprint.route("/")
        @self.blueprint.route("/<path:path>")
        def document_view(path=""):
            """
            A Flask view function to serve
            topics pulled from Discourse as documentation pages.
            """

            path = "/" + path
            self.parser.parse()

            if path == "/":
                document = self.parser.index_document
            else:
                try:
                    topic_id = self.parser.resolve_path(path)
                except RedirectFoundError as redirect:
                    return flask.redirect(redirect.target_url)
                except PathNotFoundError:
                    return flask.abort(404)

                if topic_id == self.parser.index_topic_id:
                    return flask.redirect(self.url_prefix)

                try:
                    topic = self.parser.api.get_topic(topic_id)
                except HTTPError as http_error:
                    return flask.abort(http_error.response.status_code)

                document = self.parser.parse_topic(topic)

                if category_id and topic["category_id"] != category_id:
                    forum_topic_url = (
                        f'{parser.api.base_url}{document["topic_path"]}'
                    )
                    return flask.redirect(forum_topic_url)

                if (
                    topic_id not in self.parser.url_map
                    and document["topic_path"] != path
                ):
                    return flask.redirect(document["topic_path"])

            response = flask.make_response(
                flask.render_template(
                    document_template,
                    document=document,
                    navigation=self.parser.navigation,
                    forum_url=self.parser.api.base_url,
                    metadata=self.parser.metadata,
                )
            )

            for message in self.parser.warnings:
                flask.current_app.logger.warning(message)
                response.headers.add(
                    "Warning",
                    f'199 canonicalwebteam.discourse-docs "{message}"',
                )

            return response

    def init_app(self, app):
        """
        Attach the discourse docs blueprint to the application
        at the specified `url_prefix`
        """

        app.register_blueprint(self.blueprint, url_prefix=self.url_prefix)


class EngagePages(object):
    """
    A Flask extension object to create a Blueprint
    to serve exclusively engage pages, pulling the documentation content
    from Discourse.

    :param api: A DiscourseAPI for retrieving Discourse topics
    :param index_topic_id: ID of a forum topic containing nav & URL map
    :param url_prefix: URL prefix for hosting under (Default: /engage)
    :param document_template: Path to a template for docs pages
                              (Default: docs/document.html)
    """

    def __init__(
        self,
        parser,
        document_template="engage/base.html",
        url_prefix="/engage",
        blueprint_name="engage-pages",
    ):
        self.blueprint = flask.Blueprint(blueprint_name, __name__)
        self.url_prefix = url_prefix
        self.parser = parser

        @self.blueprint.route("/sitemap.txt")
        def sitemap_view():
            """
            Show a list of all URLs in the URL map
            """

            self.parser.parse()

            urls = []

            for key, value in self.parser.url_map.items():
                if type(key) is str:
                    urls.append(flask.request.host_url.strip("/") + key)

            return (
                "\n".join(urls),
                {"Content-Type": "text/plain; charset=utf-8"},
            )

        @self.blueprint.route("/")
        @self.blueprint.route("/<path:path>")
        def document_view(path=""):
            """
            A Flask view function to serve
            topics pulled from Discourse as documentation pages.
            """

            path = "/" + path
            self.parser.parse()

            if path == "/":
                document = self.parser.index_document
            else:
                preview = flask.request.args.get("preview")

                try:
                    topic_id = self.parser.resolve_path(path)
                except PathNotFoundError:
                    return flask.abort(404)

                if topic_id == self.parser.index_topic_id:
                    return flask.redirect(self.url_prefix)

                try:
                    topic = self.parser.api.get_topic(topic_id)
                except HTTPError as http_error:
                    return flask.abort(http_error.response.status_code)

                document = self.parser.parse_topic(topic)

                if (
                    preview is None
                    and "active" in document["metadata"]
                    and document["metadata"]["active"] == "false"
                ):
                    return flask.redirect(
                        f"{self.parser.api.base_url}{document['topic_path']}"
                    )

            response = flask.make_response(
                flask.render_template(
                    document_template,
                    document=document,
                    forum_url=self.parser.api.base_url,
                    metadata=self.parser.metadata,
                    takeovers=self.parser.takeovers,
                )
            )

            return response

    def init_app(self, app):
        """
        Attach the discourse docs blueprint to the application
        at the specified `url_prefix`
        """

        app.register_blueprint(self.blueprint, url_prefix=self.url_prefix)
