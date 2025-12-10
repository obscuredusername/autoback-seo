import re
from typing import List, Dict, Optional, Union, TypedDict, Tuple
import logging
from dataclasses import dataclass
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

@dataclass
class ImageObject:
    """
    Represents an image to be injected into content.
    
    Attributes:
        url: The source URL of the image
        alt_text: Alternative text for the image (used in alt attribute)
        position: Dictionary specifying where to place the image. Can contain:
                 - 'type': 'heading' | 'paragraph' | 'top' | 'end'
                 - 'index': int (for heading/paragraph position)
                 - 'fallback_to': 'end' | 'top' | 'skip' (what to do if position not found)
                 - 'class': str (CSS class for the image, optional)
                 - 'style': str (Inline styles for the image, optional)
    """
    url: str
    alt_text: str = ""
    position: Dict[str, Union[str, int]] = None
    class_name: str = "blog-image"
    style: str = "max-width: 100%; height: auto; margin: 20px 0;"
    
    def __post_init__(self):
        # Set default position if not specified
        if self.position is None:
            self.position = {'type': 'end', 'fallback_to': 'end'}
        
        # Ensure required position fields exist
        self.position.setdefault('type', 'end')
        self.position.setdefault('fallback_to', 'end')
    
    @property
    def tag(self) -> str:
        """Generate the HTML img tag with proper escaping and attributes."""
        attrs = {
            'src': self.url,
            'alt': self.alt_text or "",
            'class': self.class_name,
            'loading': 'lazy',
            'style': self.style
        }
        
        # Filter out empty attributes
        attrs_str = ' '.join(f'{k}="{v}"' for k, v in attrs.items() if v)
        return f'<img {attrs_str}>'

class ContentUtils:
    """
    A utility class for enhancing and modifying content with various elements like images.
    Caches content analysis results for better performance.
    """
    
    def __init__(self, content: str = None):
        """
        Initialize the ContentUtils class with optional content.
        
        Args:
            content: Optional initial content to analyze and cache
        """
        self._content = content
        self._headings = None
        self._paragraphs = None
        self._link_count = None
        self._analyzed = False
        
        if content:
            self._analyze_content()
    
    @staticmethod
    def clean_html_content(html: str) -> str:
        """
        Clean and normalize HTML content, ensuring valid structure and proper backlink handling.
        Removes any content that is not wrapped in HTML tags.
        
        Args:
            html: The HTML content to clean
            
        Returns:
            str: Cleaned and validated HTML content with only wrapped content
        """
        if not html or not isinstance(html, str):
            return ""
            
        # First clean any markdown ticks
        html = ContentUtils._clean_markdown_ticks(html)
        
        # Remove any CSS styles and DOCTYPE if present
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        html = re.sub(r'<!DOCTYPE[^>]*>', '', html, flags=re.IGNORECASE)
        
        # Remove script tags and their content
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        
        # Remove HTML comments
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        
        # Remove any inline styles
        html = re.sub(r'\s+style="[^"]*"', '', html)
        
        # Remove any class and id attributes
        html = re.sub(r'\s+class="[^"]*"', '', html)
        html = re.sub(r'\s+id="[^"]*"', '', html)
        
        # Fix any remaining HTML structure issues
        if not ContentUtils.is_html_balanced(html):
            html = ContentUtils.fix_html_structure(html)
        
        # Clean up any extra whitespace and ensure proper line breaks
        html = '\n'.join(line.strip() for line in html.split('\n') if line.strip())
        
        # Ensure the content is properly wrapped in a container if it contains any HTML
        if html.strip() and not (html.strip().startswith('<') and html.strip().endswith('>')):
            html = f'<div class="content-container">\n{html}\n</div>'
        
        return html
    
    @staticmethod
    def _clean_markdown_ticks(html: str) -> str:
        """Remove markdown code ticks from HTML content."""
        return html.replace('```', '').replace('`', '')
    
    @staticmethod
    def is_html_balanced(html: str) -> bool:
        """Check if HTML tags are properly balanced."""
        stack = []
        tag_re = re.compile(r'<(/?)(\w+)[^>]*>', re.IGNORECASE)
        
        for match in tag_re.finditer(html):
            is_end_tag, tag = match.groups()
            tag = tag.lower()
            
            # Skip self-closing tags
            if tag in ('img', 'br', 'hr', 'meta', 'link', 'input', 'area', 'base', 'col', 'command', 
                      'embed', 'keygen', 'param', 'source', 'track', 'wbr'):
                continue
                
            if is_end_tag:
                if not stack:
                    return False
                if stack[-1].lower() != tag:
                    return False
                stack.pop()
            else:
                stack.append(tag)
                
        return len(stack) == 0
    
    @staticmethod
    def fix_html_structure(html: str) -> str:
        """
        Attempt to fix common HTML structure issues and ensure proper tag nesting.
        
        Args:
            html: The HTML content to fix
            
        Returns:
            str: Fixed HTML content with proper structure
        """
        if not html or not isinstance(html, str):
            return ""
            
        # First, try using BeautifulSoup for better HTML parsing if available
        try:
            from bs4 import BeautifulSoup, Tag
            
            # Use html.parser instead of lxml for better compatibility
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove any unwanted tags
            for tag in soup.find_all(['script', 'style', 'meta', 'link']):
                tag.decompose()
                
            # Ensure proper nesting
            body = soup.find('body')
            if body:
                html = str(body.decode_contents())
            else:
                html = str(soup)
                
            # If we have a complete document, extract just the body content
            if '<body' in html.lower() and '</body>' in html.lower():
                body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
                if body_match:
                    html = body_match.group(1)
                    
        except Exception as e:
            logger.warning(f"Error using BeautifulSoup to fix HTML: {str(e)}")
            # Fall back to regex-based approach
            pass
            
        # Simple tag balancing for common cases
        open_tags = []
        tag_re = re.compile(r'<(/?)(\w+)[^>]*>', re.IGNORECASE)
        
        for match in tag_re.finditer(html):
            is_end_tag, tag = match.groups()
            tag = tag.lower()
            
            # Skip self-closing tags
            if tag in ('img', 'br', 'hr', 'meta', 'link', 'input', 'area', 'base', 'col', 'command', 
                      'embed', 'keygen', 'param', 'source', 'track', 'wbr'):
                continue
                
            if is_end_tag:
                if open_tags and open_tags[-1] == tag:
                    open_tags.pop()
            else:
                open_tags.append(tag)
        
        # Close any unclosed tags in reverse order
        for tag in reversed(open_tags):
            html += f'</{tag}>'
        
        # Ensure the content is properly wrapped in a container
        if not (html.strip().startswith('<') and html.strip().endswith('>')):
            html = f'<div class="content-container">\n{html}\n</div>'
            
        return html
    
    def _analyze_content(self, content: str = None) -> None:
        """Analyze the content and cache the results."""
        if content is not None:
            self._content = content
            self._analyzed = False
            
        if self._content is None or self._analyzed:
            return
            
        # Cache headings
        self._headings = list(re.finditer(r'<h[1-6][^>]*>.*?</h[1-6]>', self._content, re.DOTALL))
        
        # Cache paragraphs
        self._paragraphs = list(re.finditer(r'<p[^>]*>.*?</p>', self._content, re.DOTALL))
        
        # Cache link count
        self._link_count = len(re.findall(r'<a\s+[^>]*href=', self._content, re.IGNORECASE))
        
        self._analyzed = True
    
    @property
    def heading_count(self) -> int:
        """Get the number of headings in the content."""
        if not self._analyzed:
            self._analyze_content()
        return len(self._headings) if self._headings else 0
    
    @property
    def paragraph_count(self) -> int:
        """Get the number of paragraphs in the content."""
        if not self._analyzed:
            self._analyze_content()
        return len(self._paragraphs) if self._paragraphs else 0
    
    @property
    def link_count(self) -> int:
        """Get the number of links in the content."""
        if not self._analyzed:
            self._analyze_content()
        return self._link_count or 0
    
    def _find_insert_position(self, content: str = None, position: Dict[str, Union[str, int]] = None) -> int:
        """
        Find the position in content where the element should be inserted.
        
        Args:
            content: Optional content to search in (uses cached content if None)
            position: Position specification with 'type' and 'index'
            
        Returns:
            int: Position index where content should be inserted
        """
        if position is None:
            position = {}
            
        pos_type = position.get('type', 'end')
        fallback = position.get('fallback_to', 'end')
        
        # Update content if provided, otherwise use cached
        if content is not None and content != self._content:
            self._content = content
            self._analyzed = False
        
        try:
            if pos_type == 'top':
                # Insert at the very beginning
                if not self._content.strip().startswith('<'):
                    return len('<p></p>\n')
                return 0
                
            elif pos_type == 'end':
                # Insert at the very end
                return len(self._content)
                
            elif pos_type == 'heading':
                # Use cached headings
                if not self.heading_count:
                    raise ValueError("No headings found in content")
                
                # Get the nth heading (0-based index)
                idx = min(position.get('index', 0), self.heading_count - 1)
                return self._headings[idx].end()
                
            elif pos_type == 'paragraph':
                # Use cached paragraphs
                if not self.paragraph_count:
                    raise ValueError("No paragraphs found in content")
                
                # Get the nth paragraph (0-based index)
                idx = min(position.get('index', 0), self.paragraph_count - 1)
                return self._paragraphs[idx].end()
                
        except Exception as e:
            logger.warning(f"Error finding position {position}: {str(e)}")
            if fallback == 'end':
                return len(self._content)
            elif fallback == 'top':
                return 0
            # For 'skip', we'll return None and handle it in the caller
            
        return None
    
    def inject_images(self, content: str, image_objects: List[ImageObject]) -> str:
        """
        Inject images into the content at specified positions.
        
        Args:
            content: The HTML content to modify
            image_objects: List of ImageObject instances with position info
            
        Returns:
            str: Modified content with images injected
        """
        if not content or not image_objects:
            logger.warning("No content or image objects provided")
            return content or ""
            
        try:
            # Update cached content
            self._content = content
            self._analyze_content()
            
            # Sort images by their desired position to maintain order
            for img_obj in sorted(image_objects, key=lambda x: x.position.get('index', 0) if isinstance(x.position, dict) else 0):
                try:
                    # Find where to insert the image (using cached content)
                    pos = self._find_insert_position(position=img_obj.position)
                    
                    if pos is not None:
                        # Insert the image with proper spacing
                        self._content = self._content[:pos].rstrip() + '\n\n' + img_obj.tag + '\n\n' + self._content[pos:].lstrip()
                        logger.info(f"Inserted image at position {img_obj.position}: {img_obj.url}")
                        
                        # Update cached positions after modification
                        self._analyzed = False
                    else:
                        logger.warning(f"Skipping image (position not found): {img_obj.url}")
                        
                except Exception as img_error:
                    logger.error(f"Error processing image {img_obj.url}: {str(img_error)}", exc_info=True)
                    continue
                    
            return self._content
            
        except Exception as e:
            logger.error(f"Error in inject_images: {str(e)}", exc_info=True)
            return content
    
    def add_video(
        self,
        content: str,
        video_url: str,
        title: str,
        position_type: str = 'heading',
        position_index: int = 15,  # 16th heading by default (0-based index 15)
        fallback_to: str = 'end'
    ) -> str:
        """
        Embeds a YouTube video into the content at a specified position.
        
        Args:
            content: The HTML content to modify
            video_url: YouTube video URL
            title: Title to display above the video
            position_type: Where to insert the video ('heading', 'paragraph', 'top', 'end')
            position_index: Index of the heading/paragraph (0-based)
            fallback_to: What to do if position not found ('end' or 'top')
            
        Returns:
            str: Modified content with embedded video
        """
        if not content or not video_url:
            logger.warning("No content or video URL provided")
            return content or ""
            
        try:
            # Convert watch URL to embed URL if needed
            embed_url = video_url.replace('watch?v=', 'embed/')
            
            # Create video embed HTML
            video_embed = f'''
<!-- YouTube Video Section -->
<div class="video-container" style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; margin: 30px 0; background: #f5f5f5; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    <h2 style="padding: 15px 20px 10px; margin: 0; color: #333; font-size: 1.5em;">Video: {title}</h2>
    <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;">
        <iframe 
            src="{embed_url}" 
            style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none;" 
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
            allowfullscreen>
        </iframe>
    </div>
    <p style="padding: 10px 20px; margin: 0; font-size: 0.9em; color: #666; background: #f9f9f9; border-top: 1px solid #eee;">
        Watch this video to learn more about {title}.
    </p>
</div>
'''
            # Find insertion position
            if position_type in ['heading', 'paragraph']:
                pattern = r'<h[1-6][^>]*>.*?</h[1-6]>' if position_type == 'heading' else r'<p[^>]*>.*?</p>'
                matches = list(re.finditer(pattern, content, re.DOTALL))
                
                if matches:
                    idx = min(position_index, len(matches) - 1)
                    target = matches[idx]
                    logger.info(f"Inserting video after {position_type} at position {idx}")
                    return content[:target.end()] + '\n' + video_embed + '\n' + content[target.end():]
                
                # Fallback if no matches found
                if fallback_to == 'top':
                    logger.warning(f"No {position_type} found, falling back to top")
                    return video_embed + '\n\n' + content
                    
            elif position_type == 'top':
                return video_embed + '\n\n' + content
                
            # Default fallback to end
            return content + '\n\n' + video_embed
            
        except Exception as e:
            logger.error(f"Error adding video: {str(e)}", exc_info=True)
            return content
    
    def remove_first_heading(self, content: str = None) -> str:
        """
        Remove the first heading (h1-h6) from the content.
        
        Args:
            content: Optional content to process (uses cached content if None)
            
        Returns:
            str: Content with the first heading removed
        """
        if content is not None and content != self._content:
            self._content = content
            
        if not self._content:
            return ""
            
        try:
            # Find the first heading
            first_heading_match = re.search(r'<h[1-6][^>]*>.*?</h[1-6]>', self._content, re.DOTALL)
            if first_heading_match:
                # Remove the first heading from content
                self._content = self._content[:first_heading_match.start()] + self._content[first_heading_match.end():]
                logger.info("Removed the first heading from content")
                return self._content
            return self._content
                
        except Exception as e:
            logger.error(f"Error removing first heading: {str(e)}", exc_info=True)
            return self._content
    
    def process_content(
        self,
        content: str,
        images: List[ImageObject] = None,
        video: Dict[str, str] = None,
        backlinks: List[str] = None,
        language: str = 'fr',
        remove_first_heading: bool = False
    ) -> str:
        """
        Process content with all enhancements in one go.
        
        Args:
            content: The HTML content to enhance
            images: List of ImageObjects to inject
            video: Dict with 'url' and 'title' for video embedding
            backlinks: List of URLs to add as backlinks
            language: Language for text content ('fr' or 'en')
            
        Returns:
            str: Enhanced content with all specified elements
        """
        if not content:
            return ""
            
        # Initialize with content and analyze
        self._content = content
        self._analyze_content()
        
        # Process images if any
        if images:
            self._content = self.inject_images(content=self._content, image_objects=images)
        
        # Process video if provided
        if video and video.get('url'):
            self._content = self.add_video(
                content=self._content,
                video_url=video['url'],
                title=video.get('title', 'Video'),
                language=language
            )
        
        # Process backlinks if provided
        if backlinks:
            self._content = self.add_backlinks(
                content=self._content,
                backlinks=backlinks,
                language=language
            )
        
        # Remove first heading if requested
        if remove_first_heading:
            self._content = self.remove_first_heading()
            
        return self._content
    
    def add_backlinks(
        self,
        content: str,
        backlinks: List[str],
        max_links: int = 3,
        min_content_links: int = 1,
        language: str = 'fr'
    ) -> str:
        """
        Add backlinks to content if it has too few links.
        
        Args:
            content: The HTML content to modify
            backlinks: List of URLs to use as backlinks
            max_links: Maximum number of backlinks to add
            min_content_links: Minimum number of links content should have
            language: Language for the link phrases ('fr' for French, 'en' for English)
            
        Returns:
            str: Modified content with added backlinks
        """
        if not content or not backlinks:
            logger.warning("No content or backlinks provided")
            return content
            
        try:
            # Count existing links in content
            href_count = len(re.findall(r'<a\s+[^>]*href=', content, re.IGNORECASE))
            
            # Skip if content already has enough links
            if href_count > min_content_links:
                logger.info(f"Content already has {href_count} links, no additional backlinks added")
                return content
                
            logger.info(f"Found only {href_count} link(s) in content, adding backlinks...")
            
            # Extract domains from backlinks that aren't already in content
            domains = []
            for url in backlinks:
                if not url:
                    continue
                    
                # Extract domain from URL
                domain_match = re.search(r'^https?://(?:www\.)?([^/]+)', url)
                if not domain_match:
                    continue
                    
                domain = domain_match.group(1)
                
                # Skip if this domain is already linked in content
                if domain not in content:
                    domains.append((domain, url))
                    if len(domains) >= max_links:
                        break
            
            if not domains:
                logger.warning("No new backlinks could be added (all domains already in content)")
                return content
                
            # Define link phrases based on language
            if language.lower() == 'fr':
                link_phrases = [
                    'Pour plus d\'informations détaillées, consultez <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.',
                    'Vous pouvez trouver des informations supplémentaires sur ce sujet sur <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.',
                    'Pour en savoir plus, visitez <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.',
                    'J\'ai trouvé un article intéressant sur <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a> à propos de ce sujet.',
                    'Selon <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>, c\'est un aspect important à considérer.'
                ]
            else:  # Default to English
                link_phrases = [
                    'For more detailed information, check out <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.',
                    'You can find additional information on this topic at <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.',
                    'To learn more, visit <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.',
                    'I found an interesting article on <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a> about this topic.',
                    'According to <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>, this is an important aspect to consider.'
                ]
            
            # Split content by <p> tags while keeping the delimiters
            paragraphs = re.split(r'(<p[^>]*>.*?</p>)', content, flags=re.DOTALL)
            new_paragraphs = []
            link_count = 0
            import random
            
            for i, para in enumerate(paragraphs):
                new_paragraphs.append(para)
                
                # After every 5th paragraph that's not empty, add a backlink if we have more to add
                if (i > 0 and i % 5 == 0 and link_count < len(domains) and 
                    para.strip() and '<p' in para and '</p>' in para):
                    domain, url = domains[link_count]
                    link_text = random.choice(link_phrases).format(url=url, domain=domain)
                    new_paragraphs.append(f'<p>{link_text}</p>')
                    link_count += 1
                    logger.info(f"Added backlink to {domain}")
            
            if link_count > 0:
                content = ''.join(new_paragraphs)
                logger.info(f"Successfully added {link_count} backlinks to the content")
            else:
                logger.warning("No suitable positions found to add backlinks")
                
            return content
            
        except Exception as e:
            logger.error(f"Error adding backlinks: {str(e)}", exc_info=True)
            return content