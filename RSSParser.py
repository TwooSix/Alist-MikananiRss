"""
Only Test in mikanani.me
"""
import feedparser
import pandas
import re

def __parseLink(entry) -> str:
    for link in entry.links:
        if link['type']=='application/x-bittorrent':
            return link['href']

def parse(rss_url:str, filter:list[re.Pattern] = []) -> pandas.DataFrame:
    data = {'title': [], 'link': [], 'pubDate': []}
    feed = feedparser.parse(rss_url)
    for each in feed.entries:
        match_result = True
        for pattern in filter:
            match_result = match_result and re.search(pattern, each.title)
        if match_result:
            data['title'].append(each.title)
            data['link'].append(__parseLink(each))
            data['pubDate'].append(each.published)
    df = pandas.DataFrame(data)
    df['pubDate'] = pandas.to_datetime(df['pubDate'], format='ISO8601')
    return df