import os
import json
import re
import asyncio
import logging
import aiohttp
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

import openai
from openai import AsyncOpenAI
from bs4 import BeautifulSoup, NavigableString
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.retrievers import TFIDFRetriever

from .prompts import (
    get_blog_content_prompt,
    get_blog_plan_prompt,
    get_blog_expansion_prompt,
    get_blog_rephrasing_prompt
)

logger = logging.getLogger(__name__)

class ContentGenerator:
    def __init__(self, chunk_size: int = 1000, max_chunks: int = 10):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.chunk_size = chunk_size
        self.max_chunks = max_chunks

    async def generate_blog_plan(self, keyword: str, language: str = "en", max_retries: int = 3, available_categories: List[str] = None) -> Dict[str, Any]:
        """
        Generate a comprehensive blog plan including title, headings, category, and image prompts
        """
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                blog_plan_prompt = get_blog_plan_prompt(keyword, language, available_categories)

                response = await self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a professional content strategist creating detailed blog outlines. Always respond with valid JSON."},
                        {"role": "user", "content": blog_plan_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=4000,
                    response_format={"type": "json_object"}
                )
                
                raw_response = response.choices[0].message.content.strip()
                
                try:
                    blog_plan = json.loads(raw_response)
                    
                    # Validate the structure
                    required_fields = ['title', 'category', 'table_of_contents', 'headings']
                    if not all(field in blog_plan for field in required_fields):
                        raise ValueError("Missing required fields in blog plan")
                    
                    return blog_plan
                except (json.JSONDecodeError, ValueError) as e:
                    last_error = f"Validation error: {str(e)}"
                    retry_count += 1
                    
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                retry_count += 1
        
        return {
            "title": keyword,
            "category": "General",
            "table_of_contents": [],
            "headings": [],
            "image_prompts": []
        }

    async def keyword_generation(
            self, 
            keyword: str, 
            language: str = "en", 
            max_retries: int = 3,
            min_length: int = 500,
            image_links: Optional[List[str]] = None,
            backlinks: Optional[List[str]] = None,
            video_link: Optional[str] = None,
            scraped_data: Optional[List[Dict[str, Any]]] = None,
            available_categories: Optional[List[str]] = None
        ) -> Dict[str, Any]:
        """
        Generate complete blog content for a given keyword.
        """
        try:
            # 1. Generate blog plan
            blog_plan = await self.generate_blog_plan(
                keyword=keyword,
                language=language,
                max_retries=max_retries,
                available_categories=available_categories or []
            )
            
            if not blog_plan or 'title' not in blog_plan:
                return {"success": False, "error": "Failed to generate valid blog plan"}

            # 2. Process scraped_data for RAG
            section_chunks = {}
            if scraped_data:
                texts = []
                if isinstance(scraped_data, list):
                    for item in scraped_data:
                        if isinstance(item, str):
                            texts.append(item)
                        elif isinstance(item, dict):
                            # Try to get text from common fields
                            for field in ['snippet', 'description', 'text', 'content', 'body']:
                                if item.get(field):
                                    texts.append(item[field])
                                    break
                
                if texts:
                    relevant_chunks = self.get_most_relevant_chunks_langchain(texts, keyword)
                    if relevant_chunks:
                        section_chunks["rag_context"] = relevant_chunks

            # 3. Generate blog content
            content_result = await self.generate_blog_content(
                keyword=keyword,
                language=language,
                blog_plan=blog_plan,
                category_names=available_categories or [],
                section_chunks=section_chunks,
                target_word_count=min_length,
                backlinks=backlinks,
                video_info={"url": video_link} if video_link else None
            )
            
            if not content_result.get("success"):
                return content_result

            content = content_result.get("content", "")
            
            # 4. Final cleaning
            cleaned_content = self._clean_html_content(content)
            
            return {
                "success": True,
                "title": blog_plan.get("title", keyword),
                "content": cleaned_content,
                "meta_description": blog_plan.get("meta_description", ""),
                "category": blog_plan.get("category", ""),
                "word_count": len(re.sub(r'<[^>]+>', ' ', cleaned_content).split())
            }
            
        except Exception as e:
            logger.error(f"Error in keyword generation: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def generate_blog_content(
        self, 
        keyword: str, 
        language: str, 
        blog_plan: Dict[str, Any], 
        category_names: List[str], 
        section_chunks: Dict[str, Any], 
        target_word_count: int = 2000,
        max_expansion_attempts: int = 2,
        backlinks: Optional[List[str]] = None,
        video_info: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate blog content using OpenAI API
        """
        logger.info(f"Target word count: {target_word_count}")
        # Ensure target_word_count is included in section_chunks for the prompt
        if not isinstance(section_chunks, dict):
            section_chunks = {}
        section_chunks['target_word_count'] = target_word_count
        content_prompt = get_blog_content_prompt(keyword, language, blog_plan, section_chunks)
        category_list = '\n'.join([f"- {cat}" for cat in category_names])

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": (
                        f"You are a professional content writer. Write ONLY in {language}.\n"
                        f"AVAILABLE CATEGORIES: {category_list}\n"
                        "Start with 'SELECTED_CATEGORY: [category name]'. Use valid HTML only."
                    )},
                    {"role": "user", "content": content_prompt}
                ],
                temperature=0.7,
                max_tokens=8000
            )
            
            generated_content = response.choices[0].message.content.strip()
            
            # Extract category and clean
            if "SELECTED_CATEGORY:" in generated_content:
                generated_content = generated_content.split("\n", 1)[1].strip()
            
            generated_content = self._clean_generated_content(generated_content)
            
            # Expansion logic if needed
            word_count = len(re.sub(r'<[^>]+>', ' ', generated_content).split())
            attempt = 0
            while word_count < target_word_count and attempt < max_expansion_attempts:
                attempt += 1
                expansion_prompt = get_blog_expansion_prompt(target_word_count, generated_content)
                exp_response = await self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": expansion_prompt}],
                    temperature=0.7,
                    max_tokens=8000
                )
                expanded = exp_response.choices[0].message.content.strip()
                generated_content += "\n" + self._clean_generated_content(expanded)
                word_count = len(re.sub(r'<[^>]+>', ' ', generated_content).split())

            return {
                "success": True,
                "content": generated_content,
                "word_count": word_count
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def rephrase_content(self, title: str, content: str, language: str = "fr") -> Dict[str, Any]:
        """
        Rephrase and expand existing content
        """
        prompt = get_blog_rephrasing_prompt(title, content, language)
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional content writer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            
            result_text = response.choices[0].message.content.strip()
            
            title_match = re.search(r'TITLE:\s*(.*?)\n', result_text, re.IGNORECASE)
            content_match = re.search(r'CONTENT:\s*(.*)', result_text, re.IGNORECASE | re.DOTALL)
            
            rephrased_title = title_match.group(1).strip() if title_match else title
            rephrased_content = content_match.group(1).strip() if content_match else result_text
            
            return {
                "success": True,
                "title": rephrased_title,
                "content": self._clean_generated_content(rephrased_content)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_most_relevant_chunks_langchain(self, texts: List[str], query: str, top_k: int = 3) -> List[str]:
        """
        Use TF-IDF to find most relevant text chunks
        """
        if not texts:
            return []
        try:
            # Filter out empty or too short texts
            valid_texts = [t for t in texts if t and len(t.strip()) > 20]
            if not valid_texts:
                return []
                
            retriever = TFIDFRetriever.from_texts(valid_texts)
            retriever.k = top_k
            docs = retriever.get_relevant_documents(query)
            return [doc.page_content for doc in docs]
        except Exception as e:
            logger.warning(f"Error in RAG retrieval: {str(e)}")
            return texts[:top_k]

    @staticmethod
    def _clean_markdown_ticks(html: str) -> str:
        return html.replace('```', '').replace('`', '')

    @staticmethod
    def _is_html_balanced(html: str) -> bool:
        stack = []
        tag_re = re.compile(r'<(/?)(\w+)[^>]*>', re.IGNORECASE)
        for match in tag_re.finditer(html):
            is_end_tag, tag = match.groups()
            tag = tag.lower()
            if tag in ('img', 'br', 'hr', 'meta', 'link', 'input', 'area', 'base', 'col', 'command', 
                      'embed', 'keygen', 'param', 'source', 'track', 'wbr'):
                continue
            if is_end_tag:
                if not stack or stack[-1] != tag:
                    return False
                stack.pop()
            else:
                stack.append(tag)
        return len(stack) == 0

    @staticmethod
    def _fix_html_structure(html: str) -> str:
        if not html:
            return ""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            return str(soup)
        except:
            return html

    def _clean_html_content(self, html: str) -> str:
        if not html:
            return ""
        html = self._clean_markdown_ticks(html)
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for script in soup(['script', 'style']):
                script.decompose()
            return str(soup)
        except:
            return html

    def _clean_generated_content(self, content: str) -> str:
        if not content:
            return ""
        content = re.sub(r'<h1[^>]*>.*?</h1>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = self._clean_html_content(content)
        if not self._is_html_balanced(content):
            content = self._fix_html_structure(content)
        return content.strip()