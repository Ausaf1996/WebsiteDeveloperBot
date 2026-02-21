from pydantic import BaseModel, field_validator


class ValidatedHTML(BaseModel):
    """Pydantic model to validate that the HTML output is a complete,
    well-formed version of the PAN Medical website."""

    content: str

    @field_validator("content")
    @classmethod
    def must_be_complete_html(cls, v):
        v_lower = v.lower()
        if "<!doctype html>" not in v_lower:
            raise ValueError("Missing <!DOCTYPE html> declaration.")
        if "<html" not in v_lower:
            raise ValueError("Missing <html> tag.")
        if "</html>" not in v_lower:
            raise ValueError("Missing closing </html> tag.")
        if "<head" not in v_lower:
            raise ValueError("Missing <head> section.")
        if "<body" not in v_lower:
            raise ValueError("Missing <body> section.")
        return v

    @field_validator("content")
    @classmethod
    def must_have_required_sections(cls, v):
        """Ensure all expected page sections still exist in the HTML."""
        required_sections = [
            "home",
            "about",
            "api",
            "formulations",
            "contrast",
            "devices",
            "chemicals",
            "animal",
            "contact",
        ]
        for section_id in required_sections:
            if f'id="{section_id}"' not in v:
                raise ValueError(
                    f"Missing required section with id=\"{section_id}\". "
                    "The update may have accidentally removed it."
                )
        return v

    @field_validator("content")
    @classmethod
    def must_have_sidebar_and_footer(cls, v):
        """Ensure sidebar navigation and footer are intact."""
        if "sidebar-wrapper" not in v:
            raise ValueError("Sidebar navigation is missing.")
        if "footer-contact" not in v:
            raise ValueError("Footer contact section is missing.")
        return v
