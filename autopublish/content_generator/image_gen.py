import os
import re
import io
import asyncio
import aiohttp
import shutil
import tempfile
import logging
from typing import Optional
from PIL import Image, ImageEnhance, ImageFile

logger = logging.getLogger(__name__)

class ImageGenerator:
    """
    A class to handle image generation, processing, and management.
    """
    
    # Semaphore to limit concurrent image generations
    image_semaphore = asyncio.Semaphore(2)
    
    async def image_generation_process(self, prompt: str, keyword: str = None, size: str = "1024x1024", max_attempts: int = 3) -> Optional[str]:
        """
        Generate an image from a prompt with retry logic.
        
        Args:
            prompt: The text prompt for image generation
            keyword: Used for generating the filename
            size: The dimensions of the image (e.g., "1024x1024")
            max_attempts: Maximum number of generation attempts
            
        Returns:
            str: Public URL of the generated image, or None if all attempts fail
        """
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"\n🔄 Attempt {attempt}/{max_attempts} - Generating image...")
                
                # Generate image
                result = await self.generate_image_bfl(prompt, size)
                
                if not result or 'url' not in result:
                    print(f"❌ Attempt {attempt} failed - No image URL in response")
                    if attempt < max_attempts:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                    
                image_url = result['url']
                print(f"✅ Image generated successfully on attempt {attempt}")
                
                # Generate filename
                image_result = await self.save_and_process_image(image_url, keyword)
                
                return image_result
                
            except Exception as e:
                print(f"⚠️  Attempt {attempt} failed: {str(e)}")
                if attempt < max_attempts:
                    retry_delay = min(5 * attempt, 30)  # Cap at 30 seconds
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                continue
        
        print("❌ All image generation attempts failed")
        return None

    def _add_watermark(self, image_path, watermark_path, output_path):
        """
        Add a watermark to the given image.
        
        Args:
            image_path: Path to the source image
            watermark_path: Path to the watermark image
            output_path: Path to save the watermarked image
            
        Returns:
            str: Path to the saved watermarked image
        """
        from PIL import Image, ImageEnhance, ImageDraw, ImageFont, ImageFilter
        import math
        
        try:
            # Open the original image and convert to RGBA
            with Image.open(image_path).convert("RGBA") as original_image, \
                 Image.open(watermark_path).convert("RGBA") as watermark:
                
                # Calculate new size (20% of the original watermark size)
                watermark_width, watermark_height = watermark.size
                scale_factor = 0.2
                new_size = (int(watermark_width * scale_factor), int(watermark_height * scale_factor))
                
                # Resize the watermark
                watermark = watermark.resize(new_size, Image.LANCZOS)
                
                # Create a transparent layer for the watermark
                watermark_layer = Image.new('RGBA', original_image.size, (0, 0, 0, 0))
                
                # Calculate tiling - we'll place watermarks diagonally
                spacing = int(max(watermark.size) * 1.5)  # Space between watermarks
                
                # Tile the watermark diagonally across the image
                for i in range(-watermark_layer.height // spacing, watermark_layer.width // spacing + 1):
                    # Calculate position for diagonal tiling
                    x = i * spacing
                    y = i * spacing
                    
                    # Create a rotated version of the watermark (45 degrees)
                    rotated_watermark = watermark.rotate(45, expand=True, resample=Image.BICUBIC)
                    
                    # Adjust opacity (50% of original)
                    alpha = rotated_watermark.split()[3]
                    alpha = ImageEnhance.Brightness(alpha).enhance(0.7)
                    rotated_watermark.putalpha(alpha)
                    
                    # Paste the watermark at the calculated position
                    watermark_layer.paste(
                        rotated_watermark,
                        (x, y),
                        rotated_watermark
                    )
                
                # Create a copy of the original image to apply the watermark
                watermarked = original_image.copy()
                
                # Composite the watermark layer onto the image
                watermarked = Image.alpha_composite(watermarked, watermark_layer)
                
                # Save the result
                watermarked.save(output_path, format='WEBP', quality=65, method=6)
                return output_path
                
        except Exception as e:
            logger.error(f"Error in _add_watermark: {str(e)}", exc_info=True)
            raise

    async def save_and_process_image(self, image_url: str, keyword: str) -> str:
        """
        Save image to disk in WebP format with 65% quality, add watermark if configured,
        and return the public URL. If saving fails, returns the original image URL.
        
        Args:
            image_url: URL of the image to download
            keyword: Keyword used for generating the filename
            
        Returns:
            str: Public URL of the saved image, or the original URL if saving fails
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"[save_and_process_image] Starting image processing")
        logger.info(f"[save_and_process_image] Original URL: {image_url}")
        logger.info(f"[save_and_process_image] Keyword: {keyword}")
        
        from PIL import Image, ImageFile, ImageEnhance
        import io
        import aiohttp
        import os
        import re
        import random
        import tempfile
        
        # Store the original URL to return if saving fails
        original_url = image_url
        logger.info(f"[save_and_process_image] Original URL stored: {original_url}")

        # Generate a safe filename
        # Get save directory from environment or use a default
        save_dir = os.getenv("IMAGES_SAVE_DIR", "/var/www/spreadtheword.fr/images")
        logger.info(f"[save_and_process_image] Using save directory: {save_dir}")

        # Generate a safe filename
        base_name = re.sub(r'[^a-zA-Z0-9]', '', str(keyword).replace(' ', ''))[:20]
        filename = f"{base_name}.webp"
        counter = 1
        filepath = ""

        # Check if file exists and find next available filename
        while True:
            filepath = os.path.join(save_dir, filename)
            if not os.path.exists(filepath):
                break
            filename = f"{base_name}{counter}.webp"
            counter += 1

        logger.info(f"[save_and_process_image] Generated filename: {filename}")
        
        try:
            # Create directory if it doesn't exist
            os.makedirs(save_dir, exist_ok=True, mode=0o777)
            filepath = os.path.join(save_dir, filename)
            
            # Check if we have write permissions
            if not os.access(os.path.dirname(filepath), os.W_OK):
                logger.warning(f"No write permissions in directory: {os.path.dirname(filepath)}")
                return original_url
            
            # If the URL is a local file path, just return it
            if image_url.startswith('file://'):
                local_path = image_url.replace('file://', '')
                logger.info(f"[save_and_process_image] Using existing local image: {local_path}")
                return local_path  # Return the local path
            
            # Set timeout for the request
            timeout = aiohttp.ClientTimeout(total=60)  # 60 seconds timeout
            
            logger.info(f"[save_and_process_image] Attempting to download image from: {image_url}")
            
            # Download the image
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(image_url) as response:
                    logger.info(f"[save_and_process_image] Image download status: {response.status}")
                    
                    if response.status != 200:
                        error_msg = f"Failed to download image: {image_url} (Status: {response.status}). Using original URL."
                        logger.error(f"[save_and_process_image] {error_msg}")
                        return original_url
                    
                    # Read the image data
                    img_data = await response.read()
                    logger.info(f"[save_and_process_image] Successfully read {len(img_data)} bytes of image data")
                    
                    try:
                        # Convert to WebP with 65% quality
                        with Image.open(io.BytesIO(img_data)) as img:
                            logger.info(f"[save_and_process_image] Opened image with mode: {img.mode}, size: {img.size}")
                            
                            # Convert to RGB if necessary (for PNG with transparency)
                            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                                logger.info("[save_and_process_image] Converting image from transparent to RGB")
                                background = Image.new('RGB', img.size, (255, 255, 255))
                                background.paste(img, mask=img.split()[-1])  # Paste using alpha channel as mask
                                img = background
                            
                            # Save the original image first
                            with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as temp_file:
                                temp_path = temp_file.name
                                img.save(temp_path, format='WEBP', quality=65, method=6)
                            
                            # Get the path to the watermark image - first check environment variable, then default location
                            watermark_path = os.getenv("WATERMARK_IMAGE_PATH")
                            if not watermark_path or not os.path.exists(watermark_path):
                                # Fall back to the default watermark location
                                watermark_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watermark', 'spreadword.webp')
                            
                            logger.info(f"[save_and_process_image] Checking watermark at: {watermark_path}")
                            
                            if os.path.exists(watermark_path):
                                try:
                                    # Verify the watermark file is readable
                                    with Image.open(watermark_path) as test_img:
                                        logger.info(f"[save_and_process_image] Watermark image is valid. Mode: {test_img.mode}, Size: {test_img.size}")
                                    
                                    # Create a temporary file for the watermarked image
                                    with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as watermarked_temp_file:
                                        watermarked_path = watermarked_temp_file.name
                                    
                                    logger.info(f"[save_and_process_image] Applying watermark from: {watermark_path}")
                                    logger.info(f"[save_and_process_image] Source image: {temp_path}, Output: {watermarked_path}")
                                    
                                    # Apply watermark
                                    self._add_watermark(temp_path, watermark_path, watermarked_path)
                                    
                                    # Verify the watermarked image was created
                                    if os.path.exists(watermarked_path) and os.path.getsize(watermarked_path) > 0:
                                        temp_path = watermarked_path  # Use the watermarked image
                                        logger.info(f"[save_and_process_image] Successfully applied watermark. New temp path: {temp_path}")
                                    else:
                                        raise Exception("Watermarked file was not created or is empty")
                                        
                                except Exception as e:
                                    logger.error(f"[save_and_process_image] Error applying watermark: {str(e)}", exc_info=True)
                                    # Clean up any partial files
                                    if 'watermarked_path' in locals() and os.path.exists(watermarked_path):
                                        try:
                                            os.unlink(watermarked_path)
                                        except:
                                            pass
                                    # Continue with unwatermarked image if watermarking fails
                            else:
                                logger.warning(f"[save_and_process_image] Watermark file not found at: {watermark_path}")
                                logger.info(f"[save_and_process_image] Current working directory: {os.getcwd()}")
                                logger.info(f"[save_and_process_image] Directory contents: {os.listdir(os.path.dirname(watermark_path))}")
                            
                            # Move the final (watermarked or original) image to the target location
                            try:
                                shutil.move(temp_path, filepath)
                                logger.info(f"[save_and_process_image] Successfully saved image to {filepath}")
                            except Exception as e:
                                logger.error(f"[save_and_process_image] Error moving file to {filepath}: {str(e)}")
                                return original_url
                        
                        # Set proper permissions
                        os.chmod(filepath, 0o644)
                        
                        # Clean up any temporary files that might be left
                        if os.path.exists(temp_path):
                            try:
                                os.unlink(temp_path)
                            except:
                                pass
                        
                        # Return the full public URL with domain
                        public_url = f"https://spreadtheword.fr/images/{filename}"  # Adjust this based on your URL structure
                        logger.info(f"[save_and_process_image] Successfully saved image to {filepath}")
                        logger.info(f"[save_and_process_image] Public URL: {public_url}")
                        
                        return public_url
                    
                    except Exception as e:
                        error_msg = f"Error processing image {image_url}: {str(e)}. Using original URL."
                        logger.error(f"[save_and_process_image] {error_msg}", exc_info=True)
                        return original_url
    
        except PermissionError as e:
            error_msg = f"Permission denied when saving image to directory: {os.path.dirname(filepath) if filepath else 'unknown'}. Error: {str(e)}"
            logger.error(f"[save_and_process_image] {error_msg}")
            logger.info("[save_and_process_image] Using original URL due to permission error")

            if os.geteuid() == 0:  # If running as root
                try:
                    os.chmod(save_dir, 0o777)
                    logger.info(f"[save_and_process_image] Attempted to fix permissions on {save_dir}")
                except Exception as perm_error:
                    logger.error(f"[save_and_process_image] Failed to fix permissions: {str(perm_error)}")
            return original_url
            
        except Exception as e:
            error_msg = f"Unexpected error processing image {image_url}: {str(e)}"
            logger.error(f"[save_and_process_image] {error_msg}", exc_info=True)
            logger.info("[save_and_process_image] Using original URL due to unexpected error")
            return original_url