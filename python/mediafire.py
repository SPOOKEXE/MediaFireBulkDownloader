
import re
import os
import aiohttp
import json
import gazpacho
import asyncio
import hashlib

from typing import Union
from tqdm import tqdm

def hash_file(filepath : str) -> str:
	hasher = hashlib.sha256()
	with open(filepath, "rb") as f:
		for chunk in iter(lambda: f.read(1024), b""):
			hasher.update(chunk)
	return hasher.hexdigest()

async def async_get(url : str) -> Union[str, None]:
	async with aiohttp.ClientSession() as session:
		response = await session.get(url, allow_redirects=True)
		response.raise_for_status()
		return await response.text()

async def download_file(url : str, filepath : str, chunk_size : int = 512) -> None:
	async with aiohttp.ClientSession() as session:
		response : aiohttp.ClientResponse = await session.get(url, allow_redirects=True)
		response.raise_for_status()
		total_size = int(response.headers.get('Content-Length', 0))
		progress_bar = tqdm(total=total_size, unit='B', unit_scale=True, desc=os.path.basename(filepath))
		with open(filepath, 'wb') as file:
			async for chunk in response.content.iter_chunked(chunk_size):
				if chunk:
					file.write(chunk)
					progress_bar.update(len(chunk))
		progress_bar.close()

async def bulk_download_files(url_filepath_tuples : list[tuple[str, str]], simultaneous : int = 3, chunk_size : int = 512) -> list[bool]:
	semaphore = asyncio.Semaphore(simultaneous)
	async def sem_download(url, filepath):
		nonlocal chunk_size
		async with semaphore:
			print(f'Starting download: {url}')
			try:
				await download_file(url, filepath, chunk_size=chunk_size)
				success = True
			except Exception as e:
				print(e)
				success = False
			print(f'Successfully downloaded: {url}')
			return success
	tasks = [sem_download(url, filepath) for (url, filepath) in url_filepath_tuples]
	print(f'Starting bulk download of {len(url_filepath_tuples)} items.')
	results = await asyncio.gather(*tasks)
	print(f'Finished bulk download of {len(url_filepath_tuples)} items.')
	return results


async def get_mfkey_from_url(url : str) -> Union[tuple[str, str], tuple[None, None]]:
	file_or_folder_pattern : str = r"mediafire\.com/(folder|file)\/([a-zA-Z0-9]+)"
	fof_matches = re.findall(file_or_folder_pattern, url)
	if fof_matches is None or len(fof_matches) == 0:
		return (None, None)
	return fof_matches[0]

async def get_mediafire_file_data(file_key : str) -> dict:
	url = f"https://www.mediafire.com/api/file/get_info.php?quick_key={file_key}&response_format=json"
	content = await async_get(url)
	return json.loads(content)['response']['file_info']

async def get_mediafire_folder_data(file_type : str, folder_key : str, chunk : int = 1, info : bool = False) -> tuple:
	return (
		f"https://www.mediafire.com/api/1.4/folder"
		f"/{'get_info' if info else 'get_content'}.php?r=utga&content_type={file_type}"
		f"&filter=all&order_by=name&order_direction=asc&chunk={chunk}"
		f"&version=1.5&folder_key={folder_key}&response_format=json"
	)

async def get_download_url_from_file(url : str) -> Union[str, None]:
	try:
		html = await async_get(url)
		soup = gazpacho.Soup(html)
		download_url = soup.find("div", {"class": "download_link"}) \
			.find("a", {"class": "input popsok"}) \
			.attrs["href"]
		return download_url
	except Exception:
		return None

async def parse_filename(filename : str) -> str:
	chars = [char if (char.isalnum() or char in "-_. ") else "-" for char in filename]
	return "".join(chars)

async def dnld_file(url : str, directory : str) -> None:
	'''Download the given MediaFire file.'''
	_, url_key = await get_mfkey_from_url(url)
	os.makedirs(directory, exist_ok=True)
	file_data : dict = await get_mediafire_file_data(url_key)
	file_first_link : str = file_data["links"]["normal_download"]
	file_dnld_link : str = await get_download_url_from_file(file_first_link)
	filename : str = await parse_filename(file_data["filename"])
	filepath = os.path.join(directory, filename)
	if os.path.exists(filepath) and file_data['hash'] == hash_file(filepath):
		return True
	await download_file(file_dnld_link, filepath, chunk_size=512)

async def dnld_folder_items(folder_key : str, directory : str) -> None:
	'''Download all items in the mediafire folder.'''
	os.makedirs(directory, exist_ok=True)
	data : list[dict] = []
	chunk = 1
	more_chunks = True
	try:
		while more_chunks:
			content : str = await async_get(await get_mediafire_folder_data('files', folder_key, chunk=chunk))
			response_json = json.loads(content)
			more_chunks = response_json["response"]["folder_content"]["more_chunks"] == "yes"
			data.extend(response_json["response"]["folder_content"]["files"])
			chunk += 1
	except:
		return
	urls : list[str] = []
	for file_data in data:
		filename : str = await parse_filename(file_data["filename"])
		filepath = os.path.join(directory, filename)
		if os.path.exists(filepath) and file_data['hash'] == hash_file(filepath):
			continue
		file_first_link : str = file_data["links"]["normal_download"]
		urls.append(file_first_link)
	tasks = [dnld_file(url, directory) for url in urls]
	print(f'Starting bulk download of {len(urls)} items.')
	results = await asyncio.gather(*tasks)
	print(f'Finished bulk download of {len(urls)} items.')
	return results

async def dnld_folder(folder_key : str, directory : str, is_root_folder : bool = False) -> None:
	'''Download the given MediaFire folder - also iterates over nested folders.'''
	if is_root_folder is True:
		folder_url : str = await get_mediafire_folder_data('folders', folder_key, info=True)
		content : str = await async_get(folder_url)
		folder_name : str = json.loads(content)["response"]["folder_info"]["name"]
		directory = os.path.join(directory, await parse_filename(folder_name))
	os.makedirs(directory, exist_ok=True)
	await dnld_folder_items(folder_key, directory)
	folder_content = json.loads(
		await async_get(await get_mediafire_folder_data("folders", folder_key))
	)["response"]["folder_content"]
	if "folders" in folder_content:
		for folder in folder_content["folders"]:
			subdir : str = os.path.join(directory, folder["name"])
			await dnld_folder(folder["folderkey"], subdir, is_root_folder=False)

async def download_url(url : str, directory : str) -> None:
	url_type, url_key = await get_mfkey_from_url(url)
	if url_type is None:
		raise ValueError('Invalid Mediafire URL!')
	if url_type == "file":
		await dnld_file(url, directory)
	elif url_type == "folder":
		await dnld_folder(url_key, directory, is_root_folder=True)
	else:
		raise ValueError('Unsupported Mediafire URL type!')

async def distributed_download_urls(urls : list[str], directory : str, simultaneous : int = 3) -> list[bool]:
	semaphore = asyncio.Semaphore(simultaneous)
	async def sem_download(url):
		async with semaphore:
			print(f'Starting download: {url}')
			try:
				await download_url(url, directory)
				success = True
			except Exception as e:
				print(e)
				success = False
			print(f'Successfully downloaded: {url}')
			return success
	tasks = [sem_download(url) for url in urls]
	print(f'Starting bulk download of {len(urls)} items.')
	results = await asyncio.gather(*tasks)
	print(f'Finished bulk download of {len(urls)} items.')
	return results
