import requests
from datetime import datetime
import json
import time
import math

from howlongtobeatpy import HowLongToBeat
import googleapiclient.discovery, googleapiclient.errors
from youtube_search import YoutubeSearch

import config


PRIO_ORIGINAL_STEAM_ICONS = False

LOAD_ALL_OPTION = "Load All"
LOAD_IMAGES_OPTION = "Load Images"

GRID_BASE_URL = "https://www.steamgriddb.com/api/v2"
IGDB_BASE_URL = "https://api.igdb.com/v4"
NOTION_BASE_URL = "https://api.notion.com/v1"

steamgrid_headers = {'Authorization': f'Bearer {config.STEAM_GRID_KEY}'}

notion_headers = headers = {
    "Authorization": "Bearer " + config.NOTION_API_KEY,
    "Content-Type": "application/json",
    "Notion-Version": "2022-02-22"
}


def igdb_headers(igdb_token):
    return {'Authorization': f'Bearer {igdb_token}', 'Client-ID': config.IGDB_CLIENT_ID}


def strip_non_ascii(string):
    stripped = (c for c in string if 0 < ord(c) < 127)
    return ''.join(stripped)


def cleanup_name(name):
    return name.replace(u"®", u"").replace(u"™", u"")


def get_yt_id_by_name(name):
    fallback_scraping = False
    if config.YT_API_KEY != "":
        youtube = googleapiclient.discovery.build('youtube', 'v3', developerKey=config.YT_API_KEY)
        yt_req = youtube.search().list(q=f'{name} Trailer', part='snippet', type='video', maxResults=1)
        try:
            video_id = yt_req.execute()['items'][0]['id']['videoId']
            return video_id
        except googleapiclient.errors.HttpError:
            fallback_scraping = True

    if fallback_scraping or config.YT_API_KEY == "":
        results = YoutubeSearch(f'{name} Trailer', max_results=10).to_dict()
        if len(results) > 0:
            return results[0]['id']

    return None


def fail_notion(page_id):
    requests.patch(
        f"{NOTION_BASE_URL}/pages/{page_id}",
        headers=notion_headers,
        data=json.dumps({
            "properties": {
                "Data Fetched": {
                    "select": {
                        "name": "Yes"
                    }
                }
            }
        })
    )

def check_and_update_notion():
    r_db = requests.post(
        f"{NOTION_BASE_URL}/databases/{config.DATABASE_ID}/query",
        headers=notion_headers,
        data=json.dumps({
            "filter": {
                "or": [
                    {
                        "property": "Data Fetched",
                        "select": {
                            "equals": LOAD_IMAGES_OPTION
                        }
                    },
                    {
                        "property": "Data Fetched",
                        "select": {
                            "equals": LOAD_ALL_OPTION
                        }
                    }
                ]

            }
        })
    )

    if r_db.status_code != 200:
        return

    for game in r_db.json()['results']:
        gd = GameData()
        rt = game['properties']['SteamID']['rich_text']
        if len(rt) == 0 or not rt[0]['plain_text'].isdigit():
            title_list = game['properties']['Name']['title']
            if len(title_list) == 0:  # failure state
                fail_notion(game['id'])
                return
            gd.fetch_data_by_name(title_list[0]['plain_text'])

        else:
            gd.fetch_data_by_steamid(rt[0]['plain_text'])

        update_data = {
            "properties": {
                "Data Fetched": {
                    "select": {
                        "name": "Yes"
                    }
                },
                "Name": {
                    "title": [
                        {"text": {"content": gd.name}}
                    ]
                },
            }
        }

        if len(gd.genres) > 0:
            dico = {12: "RPG", 11: "Real Time Strategy", 16: "Turn-based strategy"}
            update_data["properties"]["Genre"] = {}
            genres_json = []
            for genre in gd.genres:
                if genre["id"] in dico:
                    genres_json.append({"name": dico[genre["id"]].replace(",", "")})
                else:
                    genres_json.append({"name": genre["name"].replace(",", "")})
            update_data["properties"]["Genre"]["multi_select"] = genres_json

        if len(gd.themes) > 0:
            dico = {41: "4X"}
            update_data["properties"]["Theme"] = {}
            themes_json = []
            for theme in gd.themes:
                if theme["id"] in dico:
                    themes_json.append({"name": dico[theme["id"]].replace(",", "")})
                else:
                    themes_json.append({"name": theme["name"].replace(",", "")})
            update_data["properties"]["Theme"]["multi_select"] = themes_json

        if len(gd.developers) > 0:
            update_data["properties"]["Developer"] = {}
            developers_json = []
            for developer in gd.developers:
                developers_json.append({"name": developer["company"]["name"].replace(",", "")})
            update_data["properties"]["Developer"]["multi_select"] = developers_json

        if len(gd.publishers) > 0:
            update_data["properties"]["Publisher"] = {}
            publishers_json = []
            for publisher in gd.publishers:
                publishers_json.append({"name": publisher["company"]["name"].replace(",", "")})
            update_data["properties"]["Publisher"]["multi_select"] = publishers_json

        if gd.time_to_beat_all_styles is not None:
            update_data['properties']['How Long to Beat'] = {}
            update_data['properties']['How Long to Beat']['number'] = gd.time_to_beat_all_styles

        if gd.release_date_iso is not None:
            update_data['properties']['Release date'] = {
                "date": {
                    "start": gd.release_date_iso
                }
            }

        if gd.igdb_rating is not None:
            update_data['properties']["IGDB Rating"] = {
                "number": round(gd.igdb_rating, 0)
            }

        if gd.front is not None:
            update_data['properties']['Grid'] = {
                "files": [
                    {
                        "type": "external",
                        "name": "test.jpg",
                        "external": {
                            "url": gd.front
                        }
                    }
                ]
            }

        if gd.icon is not None:
            update_data['icon'] = {
                "type": "external",
                "external": {
                    "url": gd.icon
                }
            }

        if gd.hero is not None:
            update_data['cover'] = {
                "type": "external",
                "external": {
                    "url": gd.hero
                }
            }

        r_page_props = requests.patch(
            f"{NOTION_BASE_URL}/pages/{game['id']}",
            headers=notion_headers,
            data=json.dumps(update_data)
        )

        # Update page content

        page_children = []

        def text_block(text):
            return {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": text[:2000],  # Length limit on rich text content - undocumented a of now
                            }
                        }
                    ]
                }
            }

        def link_block(text, url):
            return {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": text,
                                "link": {"url": url}
                            }
                        }
                    ]
                }
            }

        def callout_block(text, emoji, color="default"):
            return {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{
                        "type": "text",
                        "text": {
                            "content": text,
                        },
                    }],
                    "icon": {
                        "emoji": emoji
                    },
                    "color": color
                }
            }

        def ext_img_block(url):
            return {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {
                        "url": url
                    }
                }
            }
        if game['properties']['Data Fetched']['select']['name'] == LOAD_ALL_OPTION:
            req_children = requests.get(
                f"{NOTION_BASE_URL}/blocks/{game['id']}/children?page_size=100", 
                headers=notion_headers)
        
            if len(req_children.json()["results"]) <= 5:

                if gd.release_date is not None:
                    page_children.append(text_block(f"Release Date: {gd.release_date}"))

                if gd.wikipedia_link is not None:
                    page_children.append(link_block("Wikipedia", gd.wikipedia_link))

                if gd.igdb_description is not None:
                    page_children.append(text_block(gd.igdb_description))

                if gd.time_to_beat_weblink is not None:

                    page_children.append(text_block(" "))
                    page_children.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "How Long To Beat Data:",
                                        "link": {"url": gd.time_to_beat_weblink}
                                    },
                                    "annotations": {
                                        "bold": False,
                                        "italic": False,
                                        "strikethrough": False,
                                        "underline": True,
                                        "code": False,
                                        "color": "default"
                                    },
                                }
                            ]
                        }
                    })

                    page_children.append({
                        "object": "block",
                        "type": "column_list",
                        "column_list": {
                            "children": [
                                {
                                    "object": "block",
                                    "type": "column",
                                    "column": {"children": [
                                        callout_block(f"Normal: {gd.time_to_beat_main}", "🏁", "yellow_background")
                                    ]}
                                },
                                {
                                    "object": "block",
                                    "type": "column",
                                    "column": {"children": [
                                        callout_block(f"Main+Extra: {gd.time_to_beat_extra}", "📌", "yellow_background")
                                    ]}
                                },
                                {
                                    "object": "block",
                                    "type": "column",
                                    "column": {"children": [
                                        callout_block(f" Completion: {gd.time_to_beat_completionist}", "✅", "yellow_background")
                                    ]}
                                },
                            ]
                        }
                    })

                if gd.yt_trailer is not None:
                    page_children.append(text_block(" "))
                    page_children.append({
                        "object": "block",
                        "type": "video",
                        "video": {
                        "type": "external",
                        "external": {
                            "url": gd.yt_trailer
                        }
                        }
                    })

                if gd.igdb_images is not None:

                    # the spacing of two separate columns looks off, so we are using rows of columns instead

                    for i in range(1, len(gd.igdb_images), 2):
                        page_children.append({
                            "object": "block",
                            "type": "column_list",
                            "column_list": {
                                "children": [
                                    {
                                        "object": "block",
                                        "type": "column",
                                        "column": {"children": [ext_img_block(gd.igdb_images[i - 1])]}
                                    },
                                    {
                                        "object": "block",
                                        "type": "column",
                                        "column": {"children": [ext_img_block(gd.igdb_images[i])]}
                                    },
                                ]
                            }
                        })

                    if len(gd.igdb_images) % 2 != 0:
                        page_children.append({
                            "object": "block",
                            "type": "column_list",
                            "column_list": {
                                "children": [
                                    {
                                        "object": "block",
                                        "type": "column",
                                        "column": {"children": [ext_img_block(gd.igdb_images[-1])]}
                                    },
                                    {
                                        "object": "block",
                                        "type": "column",
                                        "column": {"children": [text_block(" ")]}
                                    },
                                ]
                            }
                        })

                if gd.grid_credits_icon is not None:
                    page_children.append(text_block(f"Icon Credit: {gd.grid_credits_icon} on SteamGrid"))
                if gd.grid_credits_front is not None:
                    page_children.append(text_block(f"Grid Credit: {gd.grid_credits_front} on SteamGrid"))
                if gd.grid_credits_hero is not None:
                    page_children.append(text_block(f"Hero Credit: {gd.grid_credits_hero} on SteamGrid"))

                if len(page_children) == 0:
                    return

                r_page_content = requests.patch(
                    f"{NOTION_BASE_URL}/blocks/{game['id']}/children",
                    headers=notion_headers,
                    data=json.dumps({
                        'children': page_children
                    })
                )


class GameData:

    def __init__(self):

        self.name = None
        self.steamgrid_id = None

        # Image Data (Steam or SteamGrid)
        self.icon = None
        self.grid_credits_icon = None
        self.front = None
        self.grid_credits_front = None
        self.hero = None
        self.grid_credits_hero = None

        # IGDB Data
        self.release_date = None
        self.release_date_iso = None
        self.wikipedia_link = None
        self.igdb_description = None
        self.igdb_rating = None
        self.igdb_images = []
        self.genres = []
        self.themes = []
        self.developers = []
        self.publishers = []

        # Youtube Trailer link
        self.yt_trailer = None
        self.yt_trailer_video_id = None

        # HLTB
        self.time_to_beat_weblink = None
        self.time_to_beat_main = None
        self.time_to_beat_extra = None
        self.time_to_beat_completionist = None
        self.time_to_beat_all_styles = None

    @staticmethod
    def __hltb_to_string(htlb):
        floor = math.floor(htlb)
        return str(floor) + "h " + str(math.floor((htlb - floor) * 60)) + "m"

    def fetch_data_by_steamid(self, steamid):

        r = requests.get(f"http://store.steampowered.com/api/appdetails?appids={steamid}")
        if r.status_code != 200 or not r.json()[str(steamid)]['success']:
            return False # TODO Handle error outside - update notion to "failed" status

        data = r.json()[str(steamid)]['data']

        self.name = cleanup_name(data['name'])
        self.front = data['header_image']
        self.hero = f"https://steamcdn-a.akamaihd.net/steam/apps/{steamid}/library_hero.jpg"

        if PRIO_ORIGINAL_STEAM_ICONS:
            r_icon = requests.get(f"https://steamicons.adriansteffan.com/{steamid}")
            if r_icon.status_code == 200:
                self.icon = r_icon.content.decode("utf-8")
            else:
                self.icon, self.grid_credits_icon = self.request_image_by_name("icons", {})
        else:
            self.icon, self.grid_credits_icon = self.request_image_by_name("icons", {})
            if self.icon is None:
                r_icon = requests.get(f"https://steamicons.adriansteffan.com/{steamid}")
                if r_icon.status_code == 200:
                    self.icon = r_icon.content.decode("utf-8")

        self.__fetch_meta_data()

        return True

    def fetch_data_by_name(self, name):
        self.name = name

        self.icon, self.grid_credits_icon = self.request_image_by_name("icons", {})
        self.front, self.grid_credits_front = self.request_image_by_name("grids", {'dimensions': ['460x215', '920x430']})
        self.hero, self.grid_credits_hero = self.request_image_by_name("heroes", {'dimensions': ["1920x620"]})

        self.__fetch_meta_data()

    def fetch_steamgrid_id(self):
        r = requests.get(f'{GRID_BASE_URL}/search/autocomplete/{self.name}',
                         headers=steamgrid_headers)

        if r.status_code != 200 or not r.json()['success'] or len(r.json()['data']) == 0:
            return False

        self.steamgrid_id = r.json()['data'][0]['id']
        return True
    
    def request_image_by_name(self, image_type, params):
        if not self.steamgrid_id:
            if not self.fetch_steamgrid_id():
                return None, None

        r = requests.get(f'{GRID_BASE_URL}/{image_type}/game/{self.steamgrid_id}',
                         params=params,
                         headers=steamgrid_headers)
        if r.status_code != 200 or not r.json()['success'] or len(r.json()['data']) == 0:

            if image_type != 'grids':
                return None, None

            # If no other grid was found, use the yt trailer thumbnail
            self.yt_trailer_video_id = get_yt_id_by_name(self.name)
            if self.yt_trailer_video_id:
                return f"https://i.ytimg.com/vi/{self.yt_trailer_video_id}/maxresdefault.jpg", None
            else:
                return None, None

        data = r.json()['data']

        # edge case to prefer higher res icons over the first ones
        if image_type == 'icons':
            icons_filtered = list(filter(lambda icon: icon['width'] >= 64, data))
            item = data[0] if len(icons_filtered) == 0 else icons_filtered[0]
        else:
            item = data[0]

        return item['url'], item['author']['name']

    def __fetch_meta_data(self):

        # HLTB
        results = HowLongToBeat().search(self.name)

        if not results:
            results = HowLongToBeat().search(strip_non_ascii(self.name))

        if not results:
            results = HowLongToBeat().search(self.name.lower().title())

        if not results:
            results = HowLongToBeat().search(strip_non_ascii(self.name).lower().title())

        if results:
            hltb = max(results, key=lambda element: element.similarity)

            self.time_to_beat_weblink = hltb.game_web_link
            self.time_to_beat_main = GameData.__hltb_to_string(hltb.main_story)
            self.time_to_beat_extra = GameData.__hltb_to_string(hltb.main_extra)
            self.time_to_beat_completionist = GameData.__hltb_to_string(hltb.completionist)
            self.time_to_beat_all_styles = hltb.all_styles 

        # IGDB Data
        r_creds = requests.post(
            f"https://id.twitch.tv/oauth2/token?client_id={config.IGDB_CLIENT_ID}&client_secret={config.IGDB_SECRET}&grant_type=client_credentials")


        if r_creds.status_code == 200:

            igdb_token = r_creds.json()['access_token']

            r = requests.post(f'{IGDB_BASE_URL}/games',
                              data=f'fields *, genres.name, themes.name, involved_companies.company.name, involved_companies.developer, involved_companies.publisher;search "{self.name}";'.encode('utf-8'),
                              headers=igdb_headers(igdb_token))

            if r.status_code == 200 and len(r.json()) > 0:
                data = r.json()
                try:
                    igdb_game = data[next(i for i, v in enumerate(data) if v['name'].lower() == self.name.lower())]
                except StopIteration:
                    igdb_game = data[0]
                game_id = igdb_game['id']

                # Plain Meta Data
                if 'first_release_date' in igdb_game.keys():
                    self.release_date = datetime.utcfromtimestamp(int(igdb_game['first_release_date'])).strftime('%d %b %Y')
                    self.release_date_iso = datetime.utcfromtimestamp(int(igdb_game['first_release_date'])).strftime('%Y-%m-%d')
                if 'summary' in igdb_game.keys():
                    self.igdb_description = igdb_game['summary']
                if 'genres' in igdb_game.keys():
                    self.genres = igdb_game["genres"]
                if 'themes' in igdb_game.keys():
                    self.themes = igdb_game["themes"]
                if 'involved_companies' in igdb_game.keys():
                    self.developers = list(filter(lambda d: d["developer"] is True, igdb_game["involved_companies"]))
                    self.publishers = list(filter(lambda p: p["developer"] is False and p["publisher"] is True, igdb_game["involved_companies"]))
                if 'rating' in igdb_game.keys():
                    self.igdb_rating = igdb_game["rating"]
                if 'aggregated_rating' in igdb_game.keys():
                    if self.igdb_rating is not None:
                        self.igdb_rating = (self.igdb_rating + igdb_game["aggregated_rating"]) /2
                    else:
                        self.igdb_rating = igdb_game["aggregated_rating"]

                # Wikipedia Link
                r_website = requests.post(f'{IGDB_BASE_URL}/websites',
                                          data=f'fields *; where game = {game_id};',
                                          headers=igdb_headers(igdb_token))

                if r_website.status_code == 200 and len(r_website.json()) > 0:
                    w_data = r_website.json()
                    try:
                        self.wikipedia_link = w_data[next(i for i, v in enumerate(w_data) if v['category'] == 3)]['url']
                    except StopIteration:
                        pass

                # Screenshots
                r_screen = requests.post(f'{IGDB_BASE_URL}/screenshots',
                                         data=f'fields *; where game = {game_id};',
                                         headers=igdb_headers(igdb_token))

                if r_screen.status_code == 200:
                    self.igdb_images = [f"https:{s['url'].replace('t_thumb', 't_original')}" for s in r_screen.json()]

        # Youtube Trailer link
        if not self.yt_trailer_video_id:
            self.yt_trailer_video_id = get_yt_id_by_name(self.name)
        if self.yt_trailer_video_id:
            self.yt_trailer = f"https://www.youtube.com/watch?v={self.yt_trailer_video_id}"


if __name__ == "__main__":
    # Not the cleanest solution, but works for the simple purpose of this tool.
    # Delaying for x seconds after execution instead of executing every x seconds is actually the intended behavior in
    # order to avoid collisions if the Notion API takes longer x seconds to respond.
    while True:
        check_and_update_notion()
        time.sleep(3)


