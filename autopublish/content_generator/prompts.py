import json
import re


def get_blog_content_prompt(keyword, language, blog_plan, section_chunks):
    
    prompt = f'''
Create a comprehensive, well-structured blog post in {language} about: {keyword}

HTML STRUCTURE REQUIREMENTS:
1. Use proper heading hierarchy: h2 for main sections, h3 for subsections, h4 for sub-subsections
2. Include at least 3 bullet point lists with <ul> and <li> tags
3. Add at least 2 HTML tables with relevant data
4. Use <blockquote> for important quotes and expert opinions
5. Use descriptive and valid anchor text for links

CONTENT REQUIREMENTS:
1. Word Count: Minimum {section_chunks.get('target_word_count', 2000)} words
    - The content should be detailed and comprehensive
    - Ensure the word count is at least {section_chunks.get('target_word_count', 2000)} words
    - If the content is too short, expand on the existing sections
2. Structure:
   - Start with a compelling introduction (150-200 words)
   - Include at least 10 H2 sections
   - DO NOT include any <img> tags - the system will handle image insertion
   - Each H2 should have 2-3 H3 subsections
   - Each H3 can have 1-2 H4 subsections
   - Include a "Key Takeaways" section
   - Add a FAQ section with 5-7 questions
   - End with a strong conclusion
3. Content Elements:
   - Use tables to present data and comparisons
   - Include bullet points for lists and key information
   - Add blockquotes for expert opinions with proper attribution
   - Use <strong> for emphasis on important terms
   - Include relevant internal and external links with proper HTML anchor tags
   - Ensure all links have descriptive anchor text (not just 'click here')
   - Add image placeholders with descriptive alt text
   
4. Formatting:
   - Use proper HTML5 semantic elements
   - Ensure responsive design (images and videos should have max-width:100%)
   - Add proper spacing between sections
   - Use proper heading hierarchy
   - The system will handle all image styling and insertion
   - For videos, use this responsive iframe format:
   - ALL content, including Key Takeaways and FAQs, MUST be in the target language ({language})

5. SEO Best Practices:
   - Include main keyword in at least 3 subheadings
   - Use LSI keywords naturally
   - Use descriptive anchor text for links

<article>
<h2>Introduction</h2>
<p>Introduction paragraph...</p>

<h2>Main Section 1</h2>

<h3>Subsection 1.1</h3>
<p>Content with <strong>key terms</strong> and explanations...</p>

<h4>Key Points</h4>
<ul>
    <li>Point 1 with details</li>
    <li>Point 2 with explanation</li>
</ul>

<h3>Subsection 1.2</h3>
<p>More content with a relevant table:</p>

<table style="width:100%; border-collapse: collapse; margin: 20px 0;">
    <tr>
        <th style="border: 1px solid #ddd; padding: 8px;">Header 1</th>
        <th style="border: 1px solid #ddd; padding: 8px;">Header 2</th>
    </tr>
    <tr>
        <td style="border: 1px solid #ddd; padding: 8px;">Data 1</td>
        <td style="border: 1px solid #ddd; padding: 8px;">Data 2</td>
    </tr>
</table>

<blockquote>
    "Important quote or expert opinion that adds value to the content."
    <footer>- Expert Name, <cite>Source</cite></footer>
</blockquote>


<!-- Continue with more sections following the same structure -->

<!-- The following sections MUST be translated to the target language specified in the language parameter -->
<h2>(Key Takeaways - Must be in {language} dont write it up as Key Takeaways)</h2>
<ul>
    <li>Key point 1 - Must be in {language}</li>
    <li>Key point 2 - Must be in {language}</li>
</ul>

<h2>FAQs - Must be in {language}</h2>
<h3>Question 1? - Must be in {language}</h3>
<p>Detailed answer with relevant <a href="https://example.com" target="_blank" rel="noopener noreferrer">links</a> when applicable... Ensure all text is in {language}.</p>

</article>

BLOG PLAN:
{json.dumps(blog_plan, indent=2)}

SOURCE MATERIAL BY SECTION:
{json.dumps(section_chunks, indent=2)}

CRITICAL INSTRUCTIONS:
- DO NOT include any <img> tags in your response
- DO NOT include any text outside of the HTML tags
- The article that you write should be 
- Generate complete, ready-to-publish HTML content
- Follow the exact structure and formatting specified
- Ensure all HTML is properly closed and valid
- Include all required elements (tables, lists, blockquotes, etc.)
- Make the content engaging and informative
- Maintain a professional tone throughout
- Ensure content is well-researched and accurate
- Use proper heading hierarchy
- Dont add any comments of your own make publish ready post.
- Add proper spacing and formatting for readability
'''
    return prompt

def get_blog_plan_prompt(keyword: str, language: str = "en", available_categories: list = None) -> str:
    """
    Generate the blog plan prompt for OpenAI
    
    Args:
        keyword: The main keyword/topic for the blog
        language: Language for the blog content
        available_categories: List of available category names to choose from
    """
    
    # Prepare the categories text for the prompt
    categories_text = ""
    if available_categories:
        categories_text = "AVAILABLE CATEGORIES (YOU MUST CHOOSE ONE OF THESE EXACT NAMES):\n"
        categories_text += "\n".join(f"- {cat}" for cat in available_categories)
        categories_text += "\n\n"
    
    return f"""{categories_text}Create a comprehensive, SEO-friendly blog plan for the article: "{keyword}" in {language}.

IMPORTANT: You are rephrasing and expanding an existing article, not creating a new topic.

Return the response in JSON format with the following structure:
{{
    "title": "Rephrased, SEO-friendly version of the original title",
    "meta_description": "Rephrased, SEO-friendly 145-155 characters meta description",
    "category": "EXACT category name from the available categories list above",
    "table_of_contents": [
        {{
            "heading": "Descriptive, SEO-friendly main heading",
            "subheadings": [
                "Descriptive, SEO-friendly subheading",
                "Another subheading"
            ]
        }},
        ...
    ],
    "headings": [
        {{
            "title": "Descriptive, SEO-friendly main heading",
            "description": "Brief description of what this section will cover",
            "subheadings": [
                {{
                    "title": "Descriptive, SEO-friendly subheading",
                    "description": "What this sub-section covers"
                }},
                ...
            ]
        }},
        ...
    ],
    "image_prompts": [
        {{
            "prompt": "Detailed, realistic prompt for first image that matches the article content",
            "purpose": "Purpose of this image in the blog"
        }},
        {{
            "prompt": "Detailed, realistic prompt for second image that matches the article content",
            "purpose": "Purpose of this image in the blog"
        }}
    ]
}}

Requirements:
- Title should be a rephrased, SEO-friendly version of the original article title
- Category MUST be selected from the available categories list above
- DO NOT create new category names, ONLY use the ones provided
- There MUST be at least 6 to 7 main headings, each with 2–3 descriptive, SEO-friendly subheadings
- The table_of_contents must list all main headings and their subheadings using their descriptive titles
- The headings section must provide a description for each main heading and each subheading
- Image prompts MUST be detailed and specific to the article content (generate exactly two prompts)
- Image prompts should describe realistic images that would accompany this type of article
- All content should be in {language}
- Do NOT use generic numbering (like 1.1, 2.1, etc.) in any heading or subheading titles
- Focus on expanding and rephrasing the original article content

Return ONLY the JSON structure, nothing else."""

def get_blog_expansion_prompt(target_word_count: int, generated_content: str):
    """
    Generate a prompt for expanding the blog content to reach the target word count.
    
    Args:
        target_word_count: The target number of words to reach
        generated_content: The current generated content that needs expansion
        
    Returns:
        str: A prompt for expanding the blog content
    """
    # No backlink handling - all backlinks are added post-generation

    return f"""
    The following blog content needs to be expanded to reach approximately {target_word_count} words while maintaining high quality and coherence.
    
    CURRENT CONTENT:
    {generated_content}
    
    EXPANDED CONTENT (continue from where the current content left off):
    """
    
    print("✅ Expansion prompt generated")
    return prompt

def get_blog_rephrasing_prompt(original_title: str, original_content: str, language: str = "fr") -> str:
    return f"""Rephrase and extensively expand this news article in {language}. Make it comprehensive, detailed, and at least 1000 words long.

Original Title: {original_title}
Original Content: {original_content}

Requirements:
1. Rephrase EVERY SINGLE SENTENCE completely in langauge {language}
2. Expand each point with additional details, context, and explanations
3. Add relevant background information, statistics, and expert insights
4. Make the content at least 1000 words long
5. Structure with proper HTML headings (h2, h3) and paragraphs
6. Make it engaging and informative

IMPORTANT: Your response MUST start with 'TITLE:' on the very first line, and 'CONTENT:' on the very next line. Do NOT include anything else before, between, or after these sections. Do NOT include explanations, notes, or any other text. Only output:
TITLE: [rephrased title here]
CONTENT: [detailed rephrased content in HTML format here]"""