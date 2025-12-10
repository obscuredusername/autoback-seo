if blog_plan.get("image_prompts"):
                print("🔍 Injecting images into content...")
                image_generator = ImageGenerator()
                
                try:
                    # Process up to 2 image prompts
                    # for i, image_prompt in enumerate(blog_plan["image_prompts"][:2]):
                    #     prompt = image_prompt.get("prompt", "")
                    #     if not prompt:
                    #         continue
                            
                    #     print(f"🖼️  Generating image {i+1} with prompt: {prompt}")
                    #     try:
                    #         # Generate the image
                    #         # image_result = await image_generator.generate_image(prompt)
                    #         # if not image_result or not image_result.get('url'):
                    #         #     print(f"⚠️  Failed to generate image {i+1}")
                    #         #     continue
                            
                    #         BFL_image_result = image_result.get('url', '')
                    #         image_url = image_result.get('url', '')
                    #         if not image_url:
                    #             print(f"⚠️  No URL in image result for prompt {i+1}")
                    #             continue
                                
                    #         # Add to image_urls list
                    #         image_urls.append(image_url)
                    #         print(f"✅ Generated image {i+1} URL: {image_url}")
                            
                    #         # Create image HTML with the specified format
                    #         img_tag = (
                    #             f'<figure class="image">\n'
                    #             f'  <img src="{image_url}" alt="{prompt}" class="blog-image" style="max-width: 100%; height: auto; margin: 20px 0;" />\n'
                    #             f'  <figcaption style="text-align: center; font-style: italic; color: #666; margin-top: 8px;">'

                    #             f'{prompt}'

                    #             f'</figcaption>\n'
                    #             f'</figure>\n\n'
                    #         )
                            
                    #         # First image goes at the top
                    #         if i == 0:
                    #             # Add a paragraph before the image if it's at the very top
                    #             if not content.strip().startswith('<'):
                    #                 content = f'<p></p>\n{img_tag}\n' + content
                    #             else:
                    #                 # Insert after the first heading if it exists
                    #                 heading_match = re.search(r'<h1[^>]*>.*?</h1>', content, re.DOTALL)
                    #                 if heading_match:
                    #                     pos = heading_match.end()
                    #                     content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                    #                 else:
                    #                     content = img_tag + '\n' + content
                    #             print("✅ Inserted first image at the top of the content")
                    #         # Second image goes after the first paragraph or heading
                    #         elif i == 1 and content:
                    #             # Try to find the first paragraph or heading to insert after
                    #             para_match = re.search(r'<p[^>]*>.*?</p>', content, re.DOTALL) or \
                    #                        re.search(r'<h[1-6][^>]*>.*?</h[1-6]>', content, re.DOTALL)
                                
                    #             if para_match:
                    #                 # Insert after the first paragraph or heading
                    #                 pos = para_match.end()
                    #                 content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                    #                 print("✅ Inserted second image after first paragraph/heading")
                    #             else:
                    #                 # Insert in the middle of the content if no paragraph found
                    #                 mid_point = len(content) // 2
                    #                 content = content[:mid_point] + '\n' + img_tag + '\n' + content[mid_point:]
                    #                 print("✅ Inserted second image in the middle of the content")
                                    
                    #     except Exception as img_error:
                    #         print(f"⚠️  Error generating/inserting image {i+1}: {str(img_error)}")
                    #         import traceback
                    #         traceback.print_exc()
                    logger.info(f"================ {image_links}")
                    # Process images until we have 2 valid ones or run out of images
                    valid_image_count = 0
                    processed_count = 0
                    valid_images = []  # Store valid image URLs and their HTML tags
                    
                    # First pass: Collect valid images
                    for i, image_link in enumerate(image_links):
                        if valid_image_count >= 2:
                            break
                            
                        if not image_link:
                            logger.warning(f"Skipping empty image link at position {i+1}")
                            continue
                            
                        processed_count += 1
                        logger.info(f"🖼️  Processing image {processed_count}: {image_link}")
                        
                        try:
                            # Call the local API to process the image
                            import aiohttp
                            import json
                            
                            async with aiohttp.ClientSession() as session:
                                payload = {"image_links": [image_link]}
                                async with session.post(
                                    "https://nigga.cemantix.net/generator/download-image/",
                                    json=payload,
                                    headers={"Content-Type": "application/json"}
                                ) as response:
                                    if response.status == 200:
                                        result = await response.json()
                                        if result.get("status") == "completed" and result.get("results"):
                                            image_url = result["results"][0]["processed_url"]
                                            print(f"🔄 Image processing result: {image_url}")
                                            
                                            # Check if image is from the correct domain
                                            if "spreadtheword.fr" in image_url:
                                                valid_image_count += 1
                                                print(f"✅ Found valid image {valid_image_count}/2: {image_url}")
                                                
                                                # Create image HTML with the specified format using the keyword for alt text
                                                img_tag = (
                                    f'<img src="{image_url}" alt="{keyword}" class="blog-image" rel="nofollow" style="max-width: 100%; height: auto; margin: 20px 0;" />\n'
                                )
                                valid_images.append((image_url, img_tag))
                                image_urls.append(image_url)
                                if valid_image_count >= 2:
                                    print("✅ Found 2 valid images from spreadtheword.fr")
                                    break
                        except Exception as e:
                            print(f"⚠️  Error processing image {processed_count}: {str(e)}")
                            import traceback
                            traceback.print_exc()

                    # Second pass: Insert the valid images in the correct positions
                    for idx, (img_url, img_tag) in enumerate(valid_images):
                        if idx == 0:  # First image - insert at top
                            if not content.strip().startswith('<'):
                                content = f'<p></p>\n{img_tag}\n' + content
                            else:
                                # Insert after the first heading if it exists
                                heading_match = re.search(r'<h1[^>]*>.*?</h1>', content, re.DOTALL)
                                if heading_match:
                                    pos = heading_match.end()
                                    content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                                else:
                                    content = img_tag + '\n' + content
                            print(f"✅ Inserted first valid image at the top of the content: {img_url}")
                            
                        elif idx == 1:  # Second image - insert after 12th heading or at end
                            # Find all heading matches (h1 through h6)
                            heading_matches = list(re.finditer(r'<h[1-6][^>]*>.*?</h[1-6]>', content, re.DOTALL))
                            
                            # Check if we have at least 12 headings
                            if len(heading_matches) >= 12:
                                twelfth_heading = heading_matches[11]  # 0-based index, so [11] is the 12th heading
                                pos = twelfth_heading.end()
                                content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                                print(f"✅ Inserted second valid image after 12th heading: {img_url}")
                            else:
                                # Fallback to inserting after last heading if less than 12 exist
                                if heading_matches:
                                    last_heading = heading_matches[-1]
                                    pos = last_heading.end()
                                    content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                                    print(f"✅ Inserted second valid image after last heading (less than 12 headings found): {img_url}")
                                else:
                                    # If no headings found, insert at the end
                                    content = content + '\n' + img_tag + '\n'
                                    print(f"✅ Inserted second valid image at the end (no headings found): {img_url}")
                    
                    if not valid_images:
                        print("⚠️  No valid images found from spreadtheword.fr")
                
                except Exception as e:
                    print(f"⚠️  Error generating/inserting images: {str(e)}")
                    import traceback
                    traceback.print_exc()
            
            # 3.4. Remove the very first heading from content
            try:
                # Find the first heading
                first_heading_match = re.search(r'<h[1-6][^>]*>.*?</h[1-6]>', content, re.DOTALL)
                if first_heading_match:
                    # Remove the first heading from content
                    content = content[:first_heading_match.start()] + content[first_heading_match.end():]
                    print("✅ Removed the first heading from content")
            except Exception as e:
                print(f"⚠️  Error removing first heading: {str(e)}")
                import traceback
                traceback.print_exc()
            
            # 3.5. Insert video if video_link is provided
            if video_link:
                try:
                    # Find all heading matches (h1 through h6)
                    heading_matches = list(re.finditer(r'<h[1-6][^>]*>.*?</h[1-6]>', content, re.DOTALL))
                    
                    if heading_matches:
                        # Try to find the 16th heading (0-based index 15)
                        if len(heading_matches) >= 16:
                            target_heading = heading_matches[15]  # 0-based index, so [15] is the 16th heading
                            print("✅ Found 16th heading, inserting video after it")
                        else:
                            # Fallback to the last heading if less than 16 exist
                            target_heading = heading_matches[-1]
                            print(f"ℹ️ Less than 16 headings found ({len(heading_matches)}), inserting video after the last heading")
                        
                        video_embed = f'''
                        <!-- YouTube Video Section -->
                        <div class="video-container" style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; margin: 30px 0; background: #f5f5f5; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
                            <h2 style="padding: 15px 20px 10px; margin: 0; color: #333; font-size: 1.5em;">Video: {keyword}</h2>
                            <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;">
                                <iframe 
                                    src="{video_link.replace('watch?v=', 'embed/')}" 
                                    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none;" 
                                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                                    allowfullscreen>
                                </iframe>
                            </div>
                            <p style="padding: 10px 20px; margin: 0; font-size: 0.9em; color: #666; background: #f9f9f9; border-top: 1px solid #eee;">
                                Watch this video to learn more about {keyword}.
                            </p>
                        </div>
                        '''
                        # Insert the video after the target heading
                        content = content[:target_heading.end()] + '\n' + video_embed + '\n' + content[target_heading.end():]
                        print(f"✅ Successfully inserted video after heading")
                        if 'target_heading' in locals() and target_heading:
                            heading_text = target_heading.group(0)[:50] + '...' if len(target_heading.group(0)) > 50 else target_heading.group(0)
                            print(f"📌 Inserted after: {heading_text}")
                except Exception as e:
                    print(f"⚠️  Error inserting video: {str(e)}")
                    import traceback
                    traceback.print_exc()