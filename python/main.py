
from mediafire import distributed_download_urls, download_url

import re
import asyncio

def get_links_from_file(filepath : str) -> list[str]:
	url_pattern = re.compile(r'https?://[^\s]+')
	links = []
	with open(filepath, 'r', encoding='utf-8') as file:
		for line in file.readlines():
			links.extend(url_pattern.findall(line))
	return [item for item in links if item is not None]

if __name__ == '__main__':
	# from file example
	urls : list[str] = get_links_from_file("bookmarks.html")
	urls : list[str] = [item for item in urls if "www.mediafire.com" in item]
	print(len(urls))
	directory : str = 'downloads'
	simultaneous : int = 3
	_ = asyncio.run(distributed_download_urls(
		urls, directory, simultaneous=simultaneous
	))

	# using url example
	# url : str = ''
	# directory : str = 'downloads'
	# asyncio.run(download_url(url, directory))
