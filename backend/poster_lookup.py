"""External poster lookup service using TMDB, YouTube, etc."""

import asyncio
import re
from typing import Optional, Tuple
from urllib.parse import quote, parse_qs, urlparse

import aiohttp


class PosterLookup:
    """Looks up TV show/movie posters and episode stills from TMDB."""
    
    TMDB_API_KEY = '8265bd1679663a7ea12ac168da84d2e8'  # Public demo key
    TMDB_BASE = 'https://api.themoviedb.org/3'
    TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p'
    
    def __init__(self):
        self._show_cache: dict[str, int] = {}  # show name -> tmdb_id
        self._poster_cache: dict[str, str] = {}  # cache key -> poster_url
    
    async def _api_get(self, endpoint: str) -> Optional[dict]:
        """Make TMDB API request."""
        try:
            url = f'{self.TMDB_BASE}{endpoint}'
            if '?' in url:
                url += f'&api_key={self.TMDB_API_KEY}'
            else:
                url += f'?api_key={self.TMDB_API_KEY}'
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            print(f'TMDB API error: {e}')
        return None
    
    async def get_show_id(self, show_name: str) -> Optional[int]:
        """Get TMDB show ID by name."""
        if not show_name:
            return None
        
        cache_key = show_name.lower()
        if cache_key in self._show_cache:
            return self._show_cache[cache_key]
        
        data = await self._api_get(f'/search/tv?query={quote(show_name)}')
        if data and data.get('results'):
            show_id = data['results'][0]['id']
            self._show_cache[cache_key] = show_id
            return show_id
        return None
    
    async def get_season_poster(self, show_id: int, season_num: int) -> Optional[str]:
        """Get season poster URL."""
        season_data = await self._api_get(f'/tv/{show_id}/season/{season_num}')
        if season_data and season_data.get('poster_path'):
            return f"{self.TMDB_IMAGE_BASE}/w500{season_data['poster_path']}"
        return None
    
    async def find_episode(self, show_id: int, episode_title: str) -> Optional[dict]:
        """Search for an episode by title within a show."""
        if not show_id or not episode_title:
            return None
        
        episode_title_lower = episode_title.lower().strip()
        
        # Get show details to find number of seasons
        show_data = await self._api_get(f'/tv/{show_id}')
        if not show_data:
            return None
        
        num_seasons = show_data.get('number_of_seasons', 0)
        
        # Search recent seasons first (more likely to be current)
        for season_num in range(num_seasons, 0, -1):
            season_data = await self._api_get(f'/tv/{show_id}/season/{season_num}')
            if not season_data:
                continue
            
            season_poster = season_data.get('poster_path')
            
            for episode in season_data.get('episodes', []):
                ep_name = episode.get('name', '').lower().strip()
                
                # Check for match
                if (episode_title_lower == ep_name or 
                    episode_title_lower in ep_name or 
                    ep_name in episode_title_lower):
                    return {
                        'season': season_num,
                        'episode': episode.get('episode_number'),
                        'name': episode.get('name'),
                        'still_path': episode.get('still_path'),
                        'season_poster_path': season_poster,
                        'overview': episode.get('overview'),
                    }
        
        return None
    
    async def get_episode_image(self, show_name: str, episode_title: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Get episode still, season poster, and description.
        
        Returns: (episode_still_url, season_poster_url, description)
        """
        show_id = await self.get_show_id(show_name)
        if not show_id:
            return None, None, None
        
        episode = await self.find_episode(show_id, episode_title)
        if not episode:
            return None, None, None
        
        # Get episode still (landscape image from the episode)
        episode_still = None
        if episode.get('still_path'):
            episode_still = f"{self.TMDB_IMAGE_BASE}/w780{episode['still_path']}"
        
        # Get season poster (portrait poster for the season)
        season_poster = None
        if episode.get('season_poster_path'):
            season_poster = f"{self.TMDB_IMAGE_BASE}/w500{episode['season_poster_path']}"
        
        # Build description
        description = episode.get('overview', '')
        season_ep = f"S{episode['season']}E{episode['episode']}: {episode['name']}"
        full_desc = f"{season_ep}\n{description}" if description else season_ep
        
        return episode_still, season_poster, full_desc
    
    async def get_show_poster(self, show_name: str) -> Optional[str]:
        """Get show poster as fallback."""
        show_id = await self.get_show_id(show_name)
        if not show_id:
            return None
        
        show_data = await self._api_get(f'/tv/{show_id}')
        if show_data and show_data.get('poster_path'):
            return f"{self.TMDB_IMAGE_BASE}/w500{show_data['poster_path']}"
        return None
    
    async def search_movie(self, title: str, year: str = None) -> Tuple[Optional[str], Optional[str]]:
        """Search for a movie poster and description."""
        if not title:
            return None, None
        
        endpoint = f'/search/movie?query={quote(title)}'
        if year:
            endpoint += f'&year={year}'
        
        data = await self._api_get(endpoint)
        if data and data.get('results'):
            movie = data['results'][0]
            poster_url = None
            if movie.get('poster_path'):
                poster_url = f"{self.TMDB_IMAGE_BASE}/w500{movie['poster_path']}"
            return poster_url, movie.get('overview', '')
        return None, None
    
    async def search_youtube(self, title: str, channel: str = '') -> Tuple[Optional[str], Optional[str]]:
        """Search YouTube and get video thumbnail using youtube-search-python.
        
        Returns: (thumbnail_url, description)
        """
        if not title:
            return None, None
        
        try:
            from youtubesearchpython import VideosSearch
            
            # Build search query - include channel if available for better results
            query = f"{title} {channel}".strip() if channel else title
            
            # Run sync search in executor to not block
            import asyncio
            loop = asyncio.get_event_loop()
            
            def do_search():
                search = VideosSearch(query, limit=1)
                return search.result()
            
            results = await loop.run_in_executor(None, do_search)
            
            if results and results.get('result') and len(results['result']) > 0:
                video = results['result'][0]
                
                # Get best thumbnail (last one is usually highest quality)
                thumbnails = video.get('thumbnails', [])
                thumb_url = None
                if thumbnails:
                    thumb_url = thumbnails[-1].get('url')
                    # Clean up the thumbnail URL (remove size params for max quality)
                    if thumb_url and 'i.ytimg.com' in thumb_url:
                        # Extract video ID and use maxresdefault
                        video_id = video.get('id')
                        if video_id:
                            thumb_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
                
                # Build description
                channel_info = video.get('channel', {})
                author = channel_info.get('name', channel)
                duration = video.get('duration', '')
                view_count = video.get('viewCount', {})
                views_text = view_count.get('text', '') if isinstance(view_count, dict) else str(view_count)
                
                desc_parts = [f"YouTube • {author}"]
                if views_text:
                    desc_parts.append(views_text)
                if duration:
                    desc_parts.append(duration)
                
                description = " • ".join(desc_parts)
                
                return thumb_url, description
                
        except ImportError:
            print("youtube-search-python not installed")
        except Exception as e:
            print(f"YouTube search error: {e}")
        
        # Fallback description if search fails
        description = f"YouTube • {channel}" if channel else "YouTube video"
        return None, description
    
    async def find_poster(self, title: str, source_hint: str = '', app_name: str = '', app_id: str = '') -> Tuple[Optional[str], Optional[str]]:
        """Find best poster/image for the given title.
        
        Priority: App-specific -> Episode still -> Season poster -> Show poster -> Movie poster
        
        Args:
            title: The media title
            source_hint: Additional context (e.g., "Streaming on YouTube • Channel Name")
            app_name: The app name (e.g., "YouTube", "Netflix")
            app_id: The app bundle ID (e.g., "com.google.ios.youtube")
        
        Returns: (image_url, description)
        """
        if not title:
            return None, None
        
        # Detect app from app_id or app_name
        is_youtube = app_id == 'com.google.ios.youtube' or (app_name and 'youtube' in app_name.lower())
        is_netflix = app_id == 'com.netflix.Netflix' or (app_name and 'netflix' in app_name.lower())
        is_plex = app_id == 'com.plexapp.plex' or (app_name and 'plex' in app_name.lower())
        is_disney = 'disney' in (app_id or '').lower() or (app_name and 'disney' in app_name.lower())
        is_hulu = 'hulu' in (app_id or '').lower() or (app_name and 'hulu' in app_name.lower())
        is_prime = 'primevideo' in (app_id or '').lower() or (app_name and 'prime' in app_name.lower())
        
        # Extract channel/artist from source_hint
        channel = ''
        if '•' in source_hint:
            parts = source_hint.split('•')
            if len(parts) > 1:
                channel = parts[-1].strip()
        
        # YouTube - search for video thumbnail
        if is_youtube:
            # Search YouTube for the video thumbnail
            thumb_url, yt_desc = await self.search_youtube(title, channel)
            if thumb_url:
                return thumb_url, yt_desc
            
            # Fallback: try TMDB in case it's a trailer or clip from a real movie/show
            movie_poster, movie_desc = await self.search_movie(title)
            if movie_poster:
                return movie_poster, movie_desc
            
            # Try as TV show
            show_id = await self.get_show_id(title)
            if show_id:
                poster_url = await self.get_show_poster(title)
                if poster_url:
                    show_data = await self._api_get(f'/tv/{show_id}')
                    overview = show_data.get('overview', '') if show_data else ''
                    return poster_url, overview
            
            # Return YouTube description even without poster
            return None, yt_desc or f"YouTube • {channel}" if channel else "YouTube video"
        
        # Extract show name from source hint
        show_name = None
        if '•' in source_hint:
            parts = source_hint.split('•')
            if len(parts) > 1:
                show_name = parts[-1].strip()
        
        # If we have a show name, try to find the specific episode
        if show_name and show_name != title:
            episode_still, season_poster, description = await self.get_episode_image(show_name, title)
            
            # Prefer season poster first, fallback to episode still
            if season_poster:
                return season_poster, description
            if episode_still:
                return episode_still, description
            
            # Fall back to show poster
            poster_url = await self.get_show_poster(show_name)
            if poster_url:
                show_id = await self.get_show_id(show_name)
                show_data = await self._api_get(f'/tv/{show_id}') if show_id else None
                overview = show_data.get('overview', '') if show_data else ''
                return poster_url, overview
        
        # Try as TV show
        show_id = await self.get_show_id(title)
        if show_id:
            poster_url = await self.get_show_poster(title)
            show_data = await self._api_get(f'/tv/{show_id}')
            overview = show_data.get('overview', '') if show_data else ''
            return poster_url, overview
        
        # Try as movie
        return await self.search_movie(title)


# Global instance
poster_lookup = PosterLookup()
