import backoff
import json
import logging
import os
import random
import re
import requests
import string

from atlassian import Confluence
from markdown import markdown
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
from requests.auth import HTTPBasicAuth

# Set up basic configuration for logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Publisher:
    def __init__(self, url, username, password, space_id,
                 parent_page_id, page_title_suffix,
                 page_label, markdown_folder,
                 markdown_source_ref, confluence_ignorefile):
        self.confluence = Confluence(
            url=url,
            username=username,
            password=password
        )
        self.space_id = space_id
        self.parent_page_id = parent_page_id
        self.page_title_suffix = page_title_suffix
        self.page_label = page_label

        # TODO: remove and use confluence client
        self.url = url
        self.username = username
        self.password = password
        self.markdown_folder = markdown_folder
        self.markdown_source_ref = markdown_source_ref

        self.ignore_patterns = self.load_ignore_patterns(confluence_ignorefile)

    # def publish_page(self, title, content):
    #     title_with_suffix = f"{title}{self.page_title_suffix}"
    #     existing_page = self.confluence.get_page_by_title(
    #         space=self.space_id,
    #         title=title_with_suffix,
    #         expand='version'
    #     )
    #     if existing_page:
    #         return
    #         # return self.update_page(
    #         #     page_id=existing_page['id'],
    #         #     title=title_with_suffix,
    #         #     content=content
    #         # )
    #     else:
    #         return self.confluence.create_page(
    #             space=self.space_id,
    #             title=title_with_suffix,
    #             body=content,
    #             parent_id=self.parent_page_id,
    #             type='page'
    #         )
    #
    # def update_page(self, page_id, title, content):
    #     return self.confluence.update_page(
    #         page_id=page_id,
    #         title=title,
    #         body=content,
    #         type='page',
    #     )
    #
    # def delete_page(self, page_id):
    #     return self.confluence.remove_page(page_id)
    #
    #

    def create_page(self, title, content, parent_page_id):

        # descripe json query
        newPageJSONQueryString = """
        {
            "type": "page",
            "title": "DEFAULT PAGE TITLE",
            "ancestors": [
                {
                "id": 111
                }
            ],
            "space": {
                "key": "DEFAULT KEY"
            },
            "body": {
                "storage": {
                    "value": "DEFAULT PAGE CONTENT",
                    "representation": "storage"
                }
            }
        }
        """

        # load json from string
        newPagejsonQuery = json.loads(newPageJSONQueryString)

        # the key of Confluence space for content publishing
        newPagejsonQuery['space']['key'] = self.space_id

        # check of input of the ParentPageID
        if parent_page_id is None:
            # this is the root of out pages tree
            newPagejsonQuery['ancestors'][0]['id'] = self.parent_page_id
        else:
            newPagejsonQuery['ancestors'][0]['id'] = str(
                parent_page_id)  # this is the branch of our tree

        newPagejsonQuery['title'] = title + "  " + \
            self.page_title_suffix + \
            " #" + self.generate_random_string(length=3)

        # add content if the page from the input parameter
        newPagejsonQuery['body']['storage']['value'] = (
            '<ac:structured-macro ac:name="warning" ac:schema-version="1">'
            '<ac:parameter ac:name="title">Do not make changes here</ac:parameter>'
            '<ac:rich-text-body>'
            '<p>This page is autogenerated. Make changes in the '
            f'<a href="{self.markdown_source_ref}">GitHub repository</a></p>'
            '</ac:rich-text-body>'
            '</ac:structured-macro>' + content
        )

        logging.info("Create new page: " + newPagejsonQuery['title'])
        logging.debug("with content: " +
                      newPagejsonQuery['body']['storage']['value'])
        logging.debug(json.dumps(newPagejsonQuery, indent=4, sort_keys=True))

        # make call to create new page
        logging.debug("Calling URL: " + self.url+"/content/")

        response = requests.post(
            url=self.url+"/content/",
            json=newPagejsonQuery,
            auth=HTTPBasicAuth(self.username, self.password),
            verify=True)

        logging.debug(response.status_code)
        if response.status_code == 200:
            logging.info("Created successfully")
        logging.debug(json.dumps(json.loads(
            response.text), indent=4, sort_keys=True))

        # return new page id
        logging.debug("Returning created page id: " +
                      json.loads(response.text)['id'])
        return json.loads(response.text)['id']

    #
    # Function for searching pages with SEARCH TEST in the title
    #

    def search_pages(self):
        # make call using Confluence query language
        # GET /rest/api/search?cql=text~%7B%22SEARCH%20PATTERN%22%7D+and+type=page+and+space=%2212345%22&limit=1000 HTTP/1.1" 200
        # "cqlQuery": "parent=301176119 and text~{\"SEARCH PATTERN\"} and type=page and space=\"12345\""

        logging.debug("Calling URL: " + self.url + "/search?cql=parent=" + self.parent_page_id +
                      "+and+text~{\"" + self.page_title_suffix +
                      "\"}+and+type=page+and+space=\"" +
                      self.space_id +
                      "\"&limit=1000")

        def fatal_code(e):
            return not 500 <= e.response.status_code < 600

        # Exponential backoff for timeouts and server errors (500-599), fail on fatal errors

        @backoff.on_exception(backoff.expo, requests.exceptions.Timeout, max_tries=8)
        @backoff.on_exception(backoff.expo,
                              requests.exceptions.RequestException,
                              giveup=fatal_code,
                              max_tries=4)
        def get_request(url, auth):
            response = requests.get(
                url=url,
                auth=auth,
                verify=True
            )
            # Raise an HTTPError for bad responses so it can be caught by backoff or fail the script
            response.raise_for_status()
            return response

        # Modify your existing code structure to use the get_request function
        try:
            response = get_request(
                url=self.url + "/search?cql=text~{\"" + self.page_title_suffix +
                "\"}+and+type=page+and+space=\"" +
                self.space_id +
                "\"&limit=1000",
                auth=HTTPBasicAuth(self.username, self.password)
            )
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err}")
            raise SystemExit(http_err)
        except requests.exceptions.ConnectionError as conn_err:
            logger.error(f"Connection error occurred: {conn_err}")
            raise SystemExit(conn_err)
        except requests.exceptions.Timeout as timeout_err:
            # Should not reach here if `max_tries` has not been exceeded
            logger.error(
                f"Timeout error occurred after retries: {timeout_err}")
            raise SystemExit(timeout_err)
        except requests.exceptions.RequestException as req_err:
            logger.error(f"Error making request: {req_err}")
            raise SystemExit(req_err)

        logging.debug(response.status_code)
        logging.debug(response.text)
        logging.debug(json.dumps(json.loads(
            response.text), indent=4, sort_keys=True))

        # extract page's IDs from response JSON
        results = json.loads(response.text)
        foundPages = []

        for result in results['results']:
            foundPages.append(result['content']['id'])  # add found page id
            logging.info("Found page: " + result['content']['id'] +
                         " with title: " + result['content']['title'])

        logging.debug("Found pages in space " + self.space_id + " and parent page: " +
                      self.parent_page_id + " and search text: " +
                      self.page_title_suffix + ": " + str(foundPages))

        return foundPages

    def delete_pages(self, pages_id_list):

        deletedPages = []

        for page in pages_id_list:
            logging.info("Delete page: " + str(page))
            logging.debug("Calling URL: " +
                          self.url + "/content/" + str(page))
            response = requests.delete(
                url=self.url + "/content/" + str(page),
                auth=HTTPBasicAuth(self.username, self.password),
                verify=True)
            logging.debug("Delete status code: " + str(response.status_code))
            if response.status_code == 204:
                logging.info("Deleted successfully")

        return deletedPages

    def attach_file(self, page_id, attached_file):
        """
        Attach a file to a Confluence page.

        Args:
            page_id (str): ID of the Confluence page to attach the file to.
            attached_file (file): The file to be attached.

        Returns:
            str: The ID of the attached file or None if the attachment failed.
        """

        # Construct the API endpoint URL
        api_url = f"{self.url}/content/{page_id}/child/attachment"

        # Log the API call
        logging.debug(f"Calling URL: {api_url}")

        # Set up file and comment data, headers, and disable SSL verification
        attached_file_structure = {'file': attached_file}
        attached_values = {'comment': 'File was attached by the script'}

        # TODO: Why do we need nocheck? document properly or remove
        attached_header = {
            "Accept": "application/json",
            "X-Atlassian-Token": "nocheck"  # Disable token check to avoid 403 status code
        }

        # Make the POST request to attach the file
        response = requests.post(
            url=api_url,
            files=attached_file_structure,
            data=attached_values,
            auth=HTTPBasicAuth(self.username, self.password),
            headers=attached_header,
            verify=True  # Not recommended in production
        )

        # Log the response status code
        logging.debug(response.status_code)

        if response.status_code == 200:
            # Log success and parse JSON response
            logging.info("File was attached successfully")
            response_data = json.loads(response.text)
            logging.debug(json.dumps(response_data, indent=4, sort_keys=True))

            # Extract and return the ID of the attached file
            attached_file_id = response_data['results'][0]['id']
            logging.debug(f"Returning attached file id: {attached_file_id}")
            return attached_file_id
        else:
            # Log failure and return None
            logging.error("File has not been attached")
            return None

    # Confluence pages need unique titles - add some random strings at the end

    def generate_random_string(self, length=10):
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    def load_ignore_patterns(self, path):
        if not path:
            return []

        patterns = []
        try:
            with open(path, 'r') as file:
                patterns = [line.strip() for line in file if line.strip()
                            and not line.startswith('#')]
                print("loaded ignorepatterns", patterns)
        except FileNotFoundError:
            print(f"Unable to locate {path}, no patterns to ignore.")
        return patterns

    # NOTE: Move this to __init__ when refactoring to Publisher class

    # Function to check if a file matches any of the ignore patterns

    def is_ignored(self, file_path):
        spec = PathSpec.from_lines(GitWildMatchPattern, self.ignore_patterns)
        return spec.match_file(file_path)

    def folderContainsMarkdown(self, folder_path):
        for entry in os.scandir(folder_path):
            if entry.is_dir() and self.folderContainsMarkdown(entry.path):
                return True
            elif entry.is_file() and entry.name.endswith('.md'):
                return True
        return False

    def publish_folder(self, folder, parent_page_id):
        logging.info(f"Publishing folder: {folder}")
        for entry in os.scandir(folder):
            if self.is_ignored(entry.path):
                return
            if entry.is_dir():
                # Recursively publish directories that contain markdown files
                if self.folderContainsMarkdown(entry.path):
                    self.publish_directory(entry, parent_page_id)

            elif entry.is_file() and entry.name.endswith('.md'):
                # Publish only markdown files
                self.publish_file(entry, parent_page_id)

            elif entry.is_symlink():
                logging.info(f"Found symlink: {entry.path}")

    def publish_directory(self, entry, parent_page_id):
        logging.info(f"Found directory: {entry.path}")
        current_page_id = self.create_page(
            title=entry.name,
            content="<ac:structured-macro ac:name=\"children\" ac:schema-version=\"2\" "
                    "ac:macro-id=\"80b8c33e-cc87-4987-8f88-dd36ee991b15\"/>",
            parent_page_id=parent_page_id,
        )
        self.publish_folder(entry.path, current_page_id)

    def publish_file(self, entry, parent_page_id):
        logging.info(f"Found file: {entry.path}")

        if entry.name.lower().endswith('.md'):
            self.process_markdown_file(entry, parent_page_id)
        else:
            logging.info(
                f"File: {entry.path} is not a MD file. Publishing has been rejected.")

    def process_markdown_file(self, entry, parent_page_id):
        new_file_content, files_to_upload = self.process_markdown_content(
            entry.path)

        page_id_for_file_attaching = self.create_page(
            title=entry.name,
            content=markdown(new_file_content, extensions=[
                'markdown.extensions.tables', 'fenced_code']),
            parent_page_id=parent_page_id,
        )

        self.upload_attachments(files_to_upload, page_id_for_file_attaching)

    def process_markdown_content(self, file_path):
        new_file_content = ""
        files_to_upload = []

        with open(file_path, 'r', encoding="utf-8") as md_file:
            for line in md_file:
                result = re.findall(r"\A!\[.*]\((?!http)(.*)\)", line)
                if result:
                    result = result[0]
                    logging.debug(f"Found file for attaching: {result}")
                    print(f"Found file for attaching: {result}")
                    files_to_upload.append(result)
                    new_file_content += f"<ac:image> <ri:attachment ri:filename=\"{result.split('/')[-1]}\" /></ac:image>"
                else:
                    new_file_content += line

        return new_file_content, files_to_upload

    def upload_attachments(self, files_to_upload, page_id_for_file_attaching):
        if files_to_upload:
            for file in files_to_upload:
                print("file: ", file)

                # NOTE: Find the problem that this solves and fix it in a better way
                if file.startswith('/'):
                    file = '.' + file

                image_path = os.path.join(
                    self.markdown_folder, file)
                if os.path.isfile(image_path):
                    logging.info(
                        f"Attaching file: {image_path} to the page: {page_id_for_file_attaching}")
                    with open(image_path, 'rb') as attached_file:
                        self.attach_file(
                            page_id=page_id_for_file_attaching,
                            attached_file=attached_file,
                        )
                else:
                    logging.error(
                        f"File: {image_path} not found. Nothing to attach")
