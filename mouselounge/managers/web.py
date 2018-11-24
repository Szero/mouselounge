"""
The MIT License (MIT)
Copyright © 2015 RealDolos
Copyright © 2018 Szero

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the “Software”), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import logging
import html
import re
from time import time
from time import strftime
from time import localtime
from multiprocessing import Manager
from colorama import init, Fore  # , Back, Style
from cachetools import LRUCache
import isodate

from ..utils import get_text, u8str
from ..processor import Processor
from .manager import CommunityManager, GameManager

init(autoreset=True)

__all__ = ["XYoutuberCommunityManager", "XYoutuberGameManager"]

LOGGER = logging.getLogger(__name__)


class WebManager:
    needle = r"https?://(?:www\.)?(?:youtu\.be/\S+|youtube\.com/(?:v|watch|embed)\S+)"

    description = re.compile(r'itemprop="description"\s+content="(.+?)"', re.M | re.S)
    duration = re.compile(r'itemprop="duration"\s+content="(.+?)"', re.M | re.S)
    title = re.compile(r'itemprop="name"\s+content="(.+?)"', re.M | re.S)
    # needle = re.compile("^$"), 0
    cooldown = LRUCache(maxsize=10)
    timeout = 60

    # def __init__(self, *args, **kw):
    def __init__(self):
        # super().__init__(*args, **kw)
        if isinstance(self.needle, str):
            self.needle = self.needle, 0
        if self.needle and isinstance(self.needle[0], str):
            self.needle = re.compile(self.needle[0]), self.needle[1]
        self.event = Manager().Event()
        self.processor = Processor()

    @staticmethod
    def fixup(url):
        return url

    def handle_data(self, data):
        needle, group = self.needle
        now = time()
        if len(data) == 1:
            url = data[0]
            rest = None
        else:
            # skip url verification if we are in the music room
            url = f"https://www.youtube.com/watch?v={data[0]}"
            rest = data[1:]
            self.onurl(url, rest)
            return True
        for url in needle.finditer(url):
            url = url.group(group).strip()
            cd = self.cooldown.get(url, 0)
            if cd + self.timeout > now:
                print(
                    Fore.YELLOW + f"You can post {url} again "
                    f"after {self.timeout-(now-cd):.2f} seconds.\n"
                )
                continue
            self.cooldown[url] = now
            try:
                url = self.fixup(url)
                if not url:
                    continue
                if self.onurl(url, rest) is False:
                    break
            except Exception:
                LOGGER.exception("failed to process")
        return True

    def handle_vid(self, url):
        raise NotImplementedError()

    def onurl(self, url, rest):
        title, duration, desc = self.extract(
            url, self.title, self.duration, self.description
        )
        if title is None:
            return True
        title = self.unescape(title.group(1))
        if not title:
            return True
        self.handle_vid(url)
        if duration:
            duration = str(isodate.parse_duration(duration.group(1)))
        desc = self.unescape(desc.group(1))
        self.fprint(
            strftime(
                Fore.LIGHTBLUE_EX
                + "Post time: "
                + Fore.RESET
                + "%a, %d %b %Y, %H:%M:%S",
                localtime(),
            )
        )
        if rest is not None:
            self.fprint(Fore.CYAN + "Poster: " + Fore.RESET + "{}", rest[1])
        yt = Fore.RED + "Youtube: " + Fore.RESET
        self.fprint(Fore.MAGENTA + "Link: " + Fore.RESET + "{}", url)
        if duration and desc:
            self.fprint(yt + "{} ({})\n{}\n", title, duration, desc)
        elif duration:
            self.fprint(yt + "{} ({})\n", title, duration)
        elif desc:
            self.fprint(yt + "{}\n{}\n", title, desc)
        else:
            self.fprint(yt + "{}\n", title)
        return True

    @staticmethod
    def extract(url, *args):
        args = [re.compile(a) if isinstance(a, str) else a for a in args]
        text = get_text(url)
        return [a.search(text) for a in args]

    @staticmethod
    def unescape(string):
        if string:
            string = html.unescape(string.strip())
            # shit is double escaped quite often
            string = (
                string.replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"')
                .replace("&amp;", "&")
            )
            string = re.sub(r"[\s+\n]+", " ", string.replace("\r\n", "\n"))
        return string

    @staticmethod
    def fprint(string, *args, **kw):
        print(string.format(*args), **kw)


class XYoutuberCommunityManager(WebManager, CommunityManager):
    # @staticmethod
    def _fail(self, res):
        # self.event.clear()
        if res[0]:
            if int(res[0]) == -9 or int(res[0]) == 4:
                self.fprint(Fore.YELLOW + "We got a skipper!\n")
                return True
            LOGGER.error(
                "Player returned non-zero status code of %s, error trace:\n%s",
                res[0],
                u8str(res[1]),
            )
            return False
        return True

    def handle_vid(self, url):
        # When process is running already, this `set` interrupts it
        self.event.set()
        self.call_later(
            0.05,
            self.processor,
            self._fail,
            [
                "mpv",
                url,
                "--volume=50",
                "--ytdl-raw-options=format="
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/webm/mp4/best",
            ],
            {"event": self.event},
        )


class XYoutuberGameManager(WebManager, GameManager):
    @staticmethod
    def _fail(res):
        # self.event.clear()
        if res[0]:
            if int(res[0]) == 4:
                return True
            LOGGER.error(
                "Player returned non-zero status code of %s, error trace:\n%s",
                res[0],
                u8str(res[1]),
            )
            return False
        return True

    def handle_vid(self, url):
        self.event.set()
        self.call_later(
            0.05,
            self.processor,
            self._fail,
            [
                "mpv",
                url,
                "--no-video",
                "--ytdl-raw-options=format="
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/webm/mp4/best",
            ],
            {"event": self.event},
        )
