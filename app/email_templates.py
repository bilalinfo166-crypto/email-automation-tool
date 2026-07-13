"""50 Guest Posting Outreach Templates — Professional, spam-safe.
Round-robin: email #1 gets template 1, #50 gets template 50, #51 gets template 1 again.
Each template is personalized with {{variables}}.
"""

COMPANY_FOOTER = """
<div style="margin-top:30px;padding-top:15px;border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;font-family:Arial,sans-serif">
<table cellpadding="0" cellspacing="0" border="0"><tr>
<td style="padding-right:15px"><img src="https://uplyncio.com/logo.png" width="40" height="40" alt="Uplyncio" style="border-radius:8px"></td>
<td><b style="color:#1a1a2e">Uplyncio.com</b><br>Guest Posting & Niche Edit Platform<br>
<a href="mailto:info@uplyncio.com" style="color:#4f46e5;text-decoration:none">info@uplyncio.com</a></td>
</tr></table>
<p style="margin-top:12px;font-size:11px;color:#9ca3af">
<a href="{{unsubscribe_url}}" style="color:#9ca3af;text-decoration:underline">Unsubscribe</a> · 
You received this because your contact info is publicly listed on your website.
</p></div>"""

TEMPLATES = [
    # 1-10: Soft introduction
    {"subject": "Quick question about {{company_name}}",
     "body": "Hi {{first_name}},\n\nI came across {{company_name}} while researching businesses in {{industry}}. I enjoyed exploring your website and wanted to ask whether you're currently open to expanding your visibility through editorial placements on relevant industry websites.\n\nIf it's something you're considering, I'd be happy to share a few carefully selected opportunities.\n\nBest regards,\n{{sender_name}}"},

    {"subject": "A quick outreach question",
     "body": "Hi {{first_name}},\n\nI recently visited {{company_name}} and thought I'd reach out. If you're exploring content partnerships or industry publications this year, I'd be happy to share a few relevant options.\n\nIf now isn't the right time, no problem at all.\n\nKind regards,\n{{sender_name}}"},

    {"subject": "Thought I'd reach out",
     "body": "Hi {{first_name}},\n\nWhile researching companies in {{industry}}, your website stood out. I wondered if you're currently reviewing opportunities to publish content on niche-relevant websites.\n\nHappy to send a few examples if helpful.\n\nThanks,\n{{sender_name}}"},

    {"subject": "Editorial opportunities",
     "body": "Hi {{first_name}},\n\nI hope you're doing well. I came across {{company_name}} and thought there might be opportunities to place valuable content on relevant publications within your niche.\n\nLet me know if you'd like me to share a shortlist.\n\nBest,\n{{sender_name}}"},

    {"subject": "Collaboration idea",
     "body": "Hi {{first_name}},\n\nI enjoyed browsing your website. I wanted to introduce myself because we regularly work with websites across multiple industries on editorial collaborations.\n\nIf you're interested, I'd be glad to send more information.\n\nRegards,\n{{sender_name}}"},

    {"subject": "Content placement idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI noticed {{company_name}} operates in the {{industry}} space and wanted to see if you'd be open to getting featured on established industry publications.\n\nWe handle everything from topic selection to publishing.\n\nWould you like me to send a few site options?\n\nBest,\n{{sender_name}}"},

    {"subject": "Introduction from Uplyncio",
     "body": "Hi {{first_name}},\n\nMy name is {{sender_name}} and I work with businesses in {{industry}} to help them get published on high-quality websites.\n\nI thought {{company_name}} could benefit from a few well-placed articles on relevant publications.\n\nHappy to share details if you're open to it.\n\nCheers,\n{{sender_name}}"},

    {"subject": "Visibility for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI came across your website while looking at businesses in {{industry}}. I wanted to reach out because we help companies like yours appear on trusted industry websites through editorial content.\n\nWould it be worth a quick conversation?\n\nBest regards,\n{{sender_name}}"},

    {"subject": "Quick thought for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI was browsing {{company_name}} and had a quick thought. Have you considered getting your brand featured on relevant niche publications?\n\nIt's something we help businesses with, and I'd be happy to share a few options if useful.\n\nThanks,\n{{sender_name}}"},

    {"subject": "Reaching out from Uplyncio",
     "body": "Hi {{first_name}},\n\nI hope this email finds you well. I'm reaching out because I think there's a great opportunity for {{company_name}} to gain visibility through editorial placements on industry-relevant websites.\n\nLet me know if you'd like to explore this further.\n\nKind regards,\n{{sender_name}}"},

    # 11-20: Value proposition
    {"subject": "A suggestion for {{company_name}}",
     "body": "Hi {{first_name}},\n\nAfter visiting {{company_name}}, I noticed your brand could reach a wider audience through published articles on well-known {{industry}} websites.\n\nWe've helped similar businesses achieve this — happy to share specifics.\n\nBest,\n{{sender_name}}"},

    {"subject": "Something that might interest you",
     "body": "Hi {{first_name}},\n\nI work with businesses in the {{industry}} space to help them get featured in established online publications. I thought {{company_name}} might be a good fit.\n\nWould you be open to hearing more?\n\nThanks,\n{{sender_name}}"},

    {"subject": "Getting {{company_name}} featured",
     "body": "Hi {{first_name}},\n\nI came across your website and wanted to introduce a service we offer — helping brands like {{company_name}} get published on reputable websites in the {{industry}} niche.\n\nEach placement is carefully curated to match your audience.\n\nInterested in seeing some options?\n\nBest regards,\n{{sender_name}}"},

    {"subject": "Published content for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI wanted to reach out because we specialize in helping businesses like {{company_name}} get articles published on trusted websites.\n\nEvery piece is custom-written, relevant, and designed to build credibility.\n\nLet me know if you'd like to explore this.\n\nCheers,\n{{sender_name}}"},

    {"subject": "Building presence for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI've been researching companies in {{industry}} and {{company_name}} caught my attention. I wanted to share how editorial placements on niche websites could help strengthen your online presence.\n\nHappy to send a brief overview.\n\nBest,\n{{sender_name}}"},

    {"subject": "Idea for {{company_name}}'s growth",
     "body": "Hi {{first_name}},\n\nI visited {{company_name}} and thought of something that could help — getting your brand mentioned on authoritative websites in {{industry}}.\n\nWe handle the entire process from start to finish.\n\nWould you like to see a few examples?\n\nRegards,\n{{sender_name}}"},

    {"subject": "Content strategy for {{company_name}}",
     "body": "Hi {{first_name}},\n\nMany businesses in {{industry}} are investing in editorial placements to build trust and visibility online. I thought {{company_name}} could benefit from the same approach.\n\nI'd be happy to put together a few tailored options for you.\n\nBest,\n{{sender_name}}"},

    {"subject": "Featured articles for your brand",
     "body": "Hi {{first_name}},\n\nI'm reaching out because we help businesses like {{company_name}} get featured on well-known websites through professionally written articles.\n\nIt's a simple process — we handle the writing, placement, and publishing.\n\nWant me to share some relevant site options?\n\nThanks,\n{{sender_name}}"},

    {"subject": "Partnership opportunity",
     "body": "Hi {{first_name}},\n\nI came across {{company_name}} and wanted to suggest a partnership idea. We work with brands in {{industry}} to place editorial content on respected niche publications.\n\nIf this is something that interests you, I'd love to share more details.\n\nBest regards,\n{{sender_name}}"},

    {"subject": "A thought for your team",
     "body": "Hi {{first_name}},\n\nI hope you're having a great week. I wanted to share a thought — businesses in {{industry}} are seeing great results from being featured on relevant online publications.\n\nIf {{company_name}} is open to exploring this, I'd be happy to help.\n\nKind regards,\n{{sender_name}}"},

    # 21-30: Curiosity-driven
    {"subject": "Have you considered this?",
     "body": "Hi {{first_name}},\n\nHave you ever considered getting {{company_name}} featured on popular {{industry}} websites? It's a great way to reach new audiences and build credibility.\n\nI'd be glad to share how we've helped other businesses achieve this.\n\nBest,\n{{sender_name}}"},

    {"subject": "An idea worth exploring",
     "body": "Hi {{first_name}},\n\nI was looking at {{company_name}} and an idea came to mind. What if your brand was featured in articles on trusted {{industry}} publications?\n\nWe make this happen for businesses regularly. Let me know if you'd like details.\n\nThanks,\n{{sender_name}}"},

    {"subject": "Your brand on industry publications",
     "body": "Hi {{first_name}},\n\nImagine {{company_name}} being mentioned on established {{industry}} websites that your potential customers already read.\n\nThat's exactly what we help with — carefully placed editorial content on relevant publications.\n\nCurious? Let me know.\n\nBest,\n{{sender_name}}"},

    {"subject": "Something for {{company_name}} to consider",
     "body": "Hi {{first_name}},\n\nI'll keep this brief. We help companies in {{industry}} get published on reputable websites. I think {{company_name}} would be a great fit.\n\nWant me to share a few examples of what we've done recently?\n\nRegards,\n{{sender_name}}"},

    {"subject": "New opportunity for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI recently came across {{company_name}} and wanted to present an opportunity — editorial placements on high-quality {{industry}} websites.\n\nEach placement includes a custom article that highlights your expertise.\n\nShall I send over a few options?\n\nBest regards,\n{{sender_name}}"},

    {"subject": "Worth a look",
     "body": "Hi {{first_name}},\n\nQuick email — I help businesses like {{company_name}} get featured on established {{industry}} publications. No automated processes, no shortcuts — just quality placements.\n\nIf this sounds relevant, I'm happy to share more.\n\nCheers,\n{{sender_name}}"},

    {"subject": "Elevating {{company_name}}'s brand",
     "body": "Hi {{first_name}},\n\nI believe {{company_name}} has a strong story that deserves more visibility. Getting published on niche {{industry}} websites is one of the most effective ways to achieve that.\n\nWould you be interested in learning how?\n\nBest,\n{{sender_name}}"},

    {"subject": "Digital presence for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI noticed {{company_name}} has a solid foundation in {{industry}}. One thing that could take your digital presence to the next level is editorial features on well-known industry websites.\n\nLet me know if you'd like to explore this.\n\nThanks,\n{{sender_name}}"},

    {"subject": "Featured content opportunity",
     "body": "Hi {{first_name}},\n\nI wanted to reach out with a straightforward opportunity — getting {{company_name}} featured on popular {{industry}} websites through custom editorial content.\n\nIt's a proven way to build trust and visibility. Interested?\n\nBest regards,\n{{sender_name}}"},

    {"subject": "Getting your name out there",
     "body": "Hi {{first_name}},\n\nIn today's landscape, being featured on the right websites makes a real difference. I'd love to help {{company_name}} get published on relevant {{industry}} publications.\n\nHappy to share a few curated options.\n\nKind regards,\n{{sender_name}}"},

    # 31-40: Social proof
    {"subject": "What other {{industry}} brands are doing",
     "body": "Hi {{first_name}},\n\nMany businesses in {{industry}} are currently investing in editorial placements on established publications. It's become a key part of building online authority.\n\nI thought {{company_name}} might benefit from the same approach. Want to see some examples?\n\nBest,\n{{sender_name}}"},

    {"subject": "Brands like yours are doing this",
     "body": "Hi {{first_name}},\n\nI work with several companies in the {{industry}} space to get them featured on reputable websites. The response has been consistently positive.\n\nI'd love to explore whether {{company_name}} could benefit too.\n\nThanks,\n{{sender_name}}"},

    {"subject": "What's working in {{industry}} right now",
     "body": "Hi {{first_name}},\n\nI've noticed a growing trend in {{industry}} — businesses getting published on niche-relevant websites to build visibility and trust.\n\nI think {{company_name}} is perfectly positioned to benefit from this. Let me know if you'd like details.\n\nBest,\n{{sender_name}}"},

    {"subject": "A strategy that works",
     "body": "Hi {{first_name}},\n\nOne of the most effective strategies I've seen for businesses in {{industry}} is getting featured articles on established websites. It builds trust and drives relevant attention.\n\nWould {{company_name}} be open to exploring this?\n\nRegards,\n{{sender_name}}"},

    {"subject": "What I noticed about {{company_name}}",
     "body": "Hi {{first_name}},\n\nAfter looking at {{company_name}}, I noticed your brand has strong potential for editorial features on {{industry}} publications.\n\nWe've helped similar companies get published successfully. Happy to share more.\n\nCheers,\n{{sender_name}}"},

    {"subject": "Opportunity for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI help businesses in {{industry}} get their brand in front of the right audience through published articles on trusted websites.\n\nI think {{company_name}} could really benefit. Shall I put together a few options?\n\nBest regards,\n{{sender_name}}"},

    {"subject": "A proven approach",
     "body": "Hi {{first_name}},\n\nEditorial placements on niche websites have helped many brands in {{industry}} build their credibility and reach new audiences.\n\nI'd love to help {{company_name}} achieve the same. Let me know if you're interested.\n\nBest,\n{{sender_name}}"},

    {"subject": "Relevant placements for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI came across {{company_name}} and immediately thought of a few publications in {{industry}} where your brand would be a perfect fit.\n\nI'd be happy to share the list if you're interested.\n\nThanks,\n{{sender_name}}"},

    {"subject": "Your competitors are doing this",
     "body": "Hi {{first_name}},\n\nI noticed that several businesses in {{industry}} are actively getting featured on niche websites. It's becoming an essential part of building an online presence.\n\n{{company_name}} could benefit from the same strategy. Want me to share more?\n\nBest,\n{{sender_name}}"},

    {"subject": "How {{industry}} leaders build visibility",
     "body": "Hi {{first_name}},\n\nLeading companies in {{industry}} are strengthening their brand by getting published on authoritative websites. I think {{company_name}} is well-suited for similar placements.\n\nWould you like to see what's available?\n\nKind regards,\n{{sender_name}}"},

    # 41-50: Direct & brief
    {"subject": "Quick note for {{first_name}}",
     "body": "Hi {{first_name}},\n\nDo you ever explore editorial placement opportunities for {{company_name}}? We help businesses in {{industry}} get featured on relevant websites.\n\nHappy to share options if it's on your radar.\n\nBest,\n{{sender_name}}"},

    {"subject": "Brief introduction",
     "body": "Hi {{first_name}},\n\nI'll keep this short. We place editorial content for businesses on established {{industry}} websites. I think {{company_name}} could be a great fit.\n\nInterested in seeing some options?\n\nThanks,\n{{sender_name}}"},

    {"subject": "Hello from Uplyncio",
     "body": "Hi {{first_name}},\n\nI'm {{sender_name}} from Uplyncio. We help brands get published on quality websites. I came across {{company_name}} and thought we could work well together.\n\nLet me know if you'd like to learn more.\n\nBest,\n{{sender_name}}"},

    {"subject": "One quick question",
     "body": "Hi {{first_name}},\n\nIs {{company_name}} currently looking to expand its presence on {{industry}} publications?\n\nIf so, I have a few ideas that might help.\n\nRegards,\n{{sender_name}}"},

    {"subject": "Connecting with {{company_name}}",
     "body": "Hi {{first_name}},\n\nI'm reaching out to connect because I believe {{company_name}} would benefit from being featured on established {{industry}} websites.\n\nWe handle everything — you just approve.\n\nWant me to share details?\n\nBest,\n{{sender_name}}"},

    {"subject": "{{company_name}} + editorial content",
     "body": "Hi {{first_name}},\n\nHere's a simple idea — let's get {{company_name}} featured on trusted {{industry}} websites through well-crafted articles.\n\nWe take care of everything from writing to publishing.\n\nInterested?\n\nCheers,\n{{sender_name}}"},

    {"subject": "Let's connect",
     "body": "Hi {{first_name}},\n\nI've been admiring {{company_name}}'s work in {{industry}} and wanted to introduce a way to expand your reach — editorial placements on relevant niche publications.\n\nHappy to provide more information.\n\nBest regards,\n{{sender_name}}"},

    {"subject": "Suggestion for {{company_name}}",
     "body": "Hi {{first_name}},\n\nA quick suggestion — have you looked into getting {{company_name}} published on reputable {{industry}} websites? It's a great way to build authority and attract the right audience.\n\nLet me know if this interests you.\n\nThanks,\n{{sender_name}}"},

    {"subject": "Opportunity knocking",
     "body": "Hi {{first_name}},\n\nI wanted to share an opportunity with {{company_name}} — getting your brand featured on well-respected {{industry}} publications.\n\nNo commitment needed — just let me know if you'd like to explore it.\n\nBest,\n{{sender_name}}"},

    {"subject": "Worth 30 seconds of your time",
     "body": "Hi {{first_name}},\n\nThis will take just 30 seconds. We help businesses like {{company_name}} get published on quality {{industry}} websites.\n\nIf that sounds useful, I'll send over a few options. If not, no worries at all.\n\nBest regards,\n{{sender_name}}"},
]


def get_template(index: int) -> dict:
    """Round-robin: returns template for email #index (0-based)."""
    return TEMPLATES[index % len(TEMPLATES)]


def render_template(template: dict, variables: dict) -> dict:
    """Replace {{variables}} in subject and body."""
    subject = template["subject"]
    body = template["body"]
    for key, val in variables.items():
        subject = subject.replace("{{" + key + "}}", str(val))
        body = body.replace("{{" + key + "}}", str(val))
    # Add company footer
    body_html = body.replace("\n", "<br>") + COMPANY_FOOTER
    return {"subject": subject, "body": body, "body_html": body_html}
