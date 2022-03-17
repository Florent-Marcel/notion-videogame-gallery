import requests
from datetime import datetime
import json

import config

from howlongtobeatpy import HowLongToBeat
import googleapiclient.discovery

# TODO Autorun, Deployment, Documentation

PRIO_ORIGINAL_STEAM_ICONS = False

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


def check_and_update_notion():

    r_db = requests.post(
        f"{NOTION_BASE_URL}/databases/{config.DATABASE_ID}/query",
        headers=notion_headers,
        data=json.dumps({
            "filter": {
                "property": "Data Fetched",
                "select": {
                    "equals": "Waiting"
                }
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
            if len(title_list) == 0:
                # TODO Failure Condition
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

        # TODO: Update Content


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
        self.wikipedia_link = None
        self.igdb_description = None
        self.igdb_images = []

        # Youtube Trailer link
        self.yt_trailer = None

        # HLTB
        self.time_to_beat_weblink = None
        self.time_to_beat_main = None
        self.time_to_beat_extra = None
        self.time_to_beat_completionist = None

    def fetch_data_by_steamid(self, steamid):

        r = requests.get(f"http://store.steampowered.com/api/appdetails?appids={steamid}")
        if r.status_code != 200:
            return False

        data = r.json()[str(steamid)]['data']

        self.name = data['name']
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
        self.front, self.grid_credits_front = self.request_image_by_name("grids", {'dimensions': ['460x215']})
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
            return None, None

        item = r.json()['data'][0]
        return item['url'], item['author']['name']

    def __fetch_meta_data(self):

        """
        # HLTB
        results = HowLongToBeat().search(self.name)
        if results is not None and len(results) > 0:
            hltb = max(results, key=lambda element: element.similarity)

            self.time_to_beat_weblink = hltb.game_web_link
            self.time_to_beat_main = f"{hltb.gameplay_main} {hltb.gameplay_main_unit}"
            self.time_to_beat_extra = f"{hltb.gameplay_main_extra} {hltb.gameplay_main_extra_unit}"
            self.time_to_beat_completionist = f"{hltb.gameplay_completionist} {hltb.gameplay_completionist_unit}"
        """

        # IGDB Data
        r_creds = requests.post(f"https://id.twitch.tv/oauth2/token?client_id={config.IGDB_CLIENT_ID}&client_secret={config.IGDB_SECRET}&grant_type=client_credentials")

        if r_creds.status_code == 200:

            igdb_token = r_creds.json()['access_token']

            r = requests.post(f'{IGDB_BASE_URL}/games',
                             data=f'fields *; search "{self.name}";',
                             headers=igdb_headers(igdb_token))

            if r.status_code == 200 and len(r.json()) > 0:
                data = r.json()
                try:
                    igdb_game = data[next(i for i, v in enumerate(data) if v['name'].lower() == self.name.lower())]
                except StopIteration:
                    igdb_game = data[0]
                game_id = igdb_game['id']

                # Plain Meta Data
                self.release_date = datetime.utcfromtimestamp(int(igdb_game['first_release_date'])).strftime('%d %b %Y')
                self.igdb_description = igdb_game['summary']

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
        youtube = googleapiclient.discovery.build('youtube', 'v3', developerKey=config.YT_API_KEY)
        yt_req = youtube.search().list(q=f'{self.name} Trailer', part='snippet', type='video')

        video_id = yt_req.execute()['items'][0]['id']['videoId']
        self.yt_trailer = f"https://www.youtube.com/watch?v={video_id}"


if __name__ == "__main__":
    check_and_update_notion()

