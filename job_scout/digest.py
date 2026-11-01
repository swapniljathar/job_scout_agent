"""Daily email digest rendering."""
from datetime import datetime
from html import escape


def generate_email_digest_html(processed_jobs, user_name="Swapnil"):
    """
    Generates the styled HTML email summary matching the n8n Gmail node.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#222;max-width:750px;">
  <h2 style="color:#1a73e8;border-bottom:2px solid #1a73e8;padding-bottom:8px;">🎯 Your Tailored ATS Resumes Are Ready ({len(processed_jobs)})</h2>
  <p>Generated for <strong>{user_name}</strong> on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
  <table style="border-collapse:collapse;width:100%;margin-top:16px;">
    <thead>
      <tr style="background:#f8f9fa;">
        <th style="text-align:left;padding:10px;border-bottom:2px solid #ddd;">Company</th>
        <th style="text-align:left;padding:10px;border-bottom:2px solid #ddd;">Role</th>
        <th style="text-align:left;padding:10px;border-bottom:2px solid #ddd;">Posted</th>
        <th style="text-align:left;padding:10px;border-bottom:2px solid #ddd;">Job Link</th>
        <th style="text-align:left;padding:10px;border-bottom:2px solid #ddd;">Status</th>
      </tr>
    </thead>
    <tbody>
"""
    for job in processed_jobs:
        html += f"""      <tr>
        <td style="padding:10px;border-bottom:1px solid #eee;font-weight:700;">{escape(str(job.get('company', '')))}</td>
        <td style="padding:10px;border-bottom:1px solid #eee;">{escape(str(job.get('title', '')))}</td>
        <td style="padding:10px;border-bottom:1px solid #eee;">{escape(str(job.get('postedAt', today)))}</td>
        <td style="padding:10px;border-bottom:1px solid #eee;"><a href="{escape(job.get('jobLink') or '#', quote=True)}" style="color:#1a73e8;">🔗 View Job</a></td>
        <td style="padding:10px;border-bottom:1px solid #eee;"><span style="color:#0f9d58;font-weight:600;">✓ ATS Tailored</span></td>
      </tr>
"""
    html += f"""    </tbody>
  </table>
  <p style="color:#888;font-size:11px;margin-top:20px;border-top:1px solid #eee;padding-top:8px;">
    Automated Job Scout & Resume Customizer Agent • {today}
  </p>
</div>"""
    return html
