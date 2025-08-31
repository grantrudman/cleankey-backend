from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
import os
import requests
import math
import asyncio
import logging
from supabase import create_client, Client
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Cleaning Quote API",
    description="Short-term rental cleaning quote calculator with email automation",
    version="1.0.0"
)

# CORS middleware for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://cleankey-frontend.vercel.app", "https://your-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables (set these in your deployment)
# 🚩 UPDATE THESE LINES WITH YOUR SUPABASE CREDENTIALS 🚩
SUPABASE_URL = os.getenv("SUPABASE_URL")  # Your Supabase project URL
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")  # Your Supabase anon/public key
BREVO_API_KEY = os.getenv("BREVO_API_KEY")  # Your Brevo (Sendinblue) API key
COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "cleankey.business@gmail.com")

# Calendly link for scheduling
calendly_link = os.getenv("CALENDLY_LINK")

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {e}")
    supabase = None

# Pydantic models - UPDATED to match frontend form fields exactly
class QuoteRequest(BaseModel):
    # Contact Info - UPDATED to match frontend
    full_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    
    # Property Address Info - UPDATED to match frontend field names
    address: str = Field(..., min_length=1, max_length=500)  # Property address from frontend
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=50)
    zip_code: str = Field(..., min_length=5, max_length=10)
    
    # Property Features - UPDATED to match frontend exactly
    beds: int = Field(0, ge=0, le=20)
    bedrooms: int = Field(0, ge=0, le=20)
    full_bathrooms: int = Field(0, ge=0, le=10)
    half_bathrooms: int = Field(0, ge=0, le=10)
    living_rooms: int = Field(0, ge=0, le=10)
    kitchens: int = Field(1, ge=1, le=5)
    
    # Square footage - UPDATED to match frontend
    carpet_area: float = Field(0, ge=0)
    hard_floors_area: float = Field(0, ge=0)
    
    # Additional features - UPDATED to match frontend
    exterior_features: int = Field(0, ge=0, le=20)
    extra_spaces: int = Field(0, ge=0, le=20)
    pets_allowed: bool = False

class QuoteBreakdown(BaseModel):
    labor_hours: float
    required_cleaners: int
    estimated_actual_time: float  # NEW KPI: total time / cleaners
    base_hourly_rate: float  # Store base rate
    coli_index: float
    adjusted_hourly_rate: float
    raw_cost: float
    profit_margin_percentage: float  # Store the percentage
    profit_margin_amount: float  # Store the dollar amount
    flat_fee: float
    final_quote: float
    max_hours_per_cleaner: float  # Store the constant
    pet_multiplier_applied: bool  # Whether multiplier was used
    pet_multiplier_rate: float  # Store the multiplier

class QuoteResponse(BaseModel):
    quote: float
    breakdown: QuoteBreakdown
    message: str

# Updated COLI data (Cost of Living Index by zip code)
# Focused on Minnesota, Virginia, Washington DC, and Maryland
# Index where 100 = national average
COLI_DATA = {
    # WASHINGTON DC (High COLI - 125-135)
    "20001": 132, "20002": 128, "20003": 135, "20004": 138, "20005": 140,
    "20006": 142, "20007": 145, "20008": 148, "20009": 135, "20010": 130,
    "20011": 125, "20012": 128, "20015": 145, "20016": 150, "20017": 128,
    "20018": 125, "20019": 122, "20020": 118, "20024": 138, "20032": 120,
    "20036": 145, "20037": 148, "20052": 140, "20057": 142, "20064": 135,
    "20071": 140, "20090": 138, "20204": 140, "20500": 145,
    
    # MARYLAND
    # Baltimore Metro Area (Moderate-High COLI - 108-125)
    "21201": 115, "21202": 118, "21205": 110, "21206": 108, "21207": 105,
    "21208": 120, "21209": 125, "21210": 118, "21211": 108, "21212": 115,
    "21213": 105, "21214": 108, "21215": 105, "21216": 102, "21217": 100,
    "21218": 112, "21219": 108, "21220": 110, "21221": 108, "21222": 110,
    "21224": 112, "21225": 105, "21227": 108, "21228": 112, "21229": 110,
    "21230": 115, "21231": 118, "21234": 108, "21235": 105, "21236": 110,
    "21237": 105, "21239": 110, "21244": 115, "21250": 112, "21286": 115,
    
    # Montgomery County, MD (High COLI - 125-145)
    "20812": 140, "20814": 145, "20815": 148, "20816": 142, "20817": 140,
    "20818": 138, "20832": 135, "20833": 138, "20837": 140, "20838": 142,
    "20841": 135, "20842": 138, "20850": 132, "20851": 130, "20852": 135,
    "20853": 138, "20854": 135, "20855": 132, "20871": 128, "20872": 130,
    "20874": 132, "20876": 130, "20877": 128, "20878": 130, "20879": 132,
    "20880": 135, "20882": 138, "20886": 130, "20895": 128, "20896": 135,
    "20901": 125, "20902": 128, "20903": 125, "20904": 122, "20905": 125,
    "20906": 128, "20910": 130, "20912": 125,
    
    # Prince George's County, MD (Moderate COLI - 110-125)
    "20705": 115, "20706": 118, "20707": 115, "20708": 112, "20710": 115,
    "20712": 112, "20715": 118, "20716": 115, "20717": 112, "20720": 115,
    "20721": 118, "20722": 115, "20724": 112, "20737": 118, "20740": 120,
    "20743": 115, "20744": 112, "20745": 118, "20746": 115, "20747": 112,
    "20748": 115, "20770": 122, "20774": 118, "20782": 115, "20783": 112,
    "20785": 118, "20787": 120, "20788": 115, "20794": 112,
    
    # Anne Arundel County, MD (Moderate-High COLI - 115-130)
    "21037": 125, "21054": 122, "21060": 125, "21061": 128, "21076": 120,
    "21090": 118, "21108": 115, "21113": 118, "21114": 120, "21122": 118,
    "21140": 125, "21144": 120, "21146": 122, "21401": 128, "21403": 125,
    "21405": 130, "21409": 125, "21412": 122,
    
    # Frederick County, MD (Moderate COLI - 108-118)
    "21701": 115, "21702": 112, "21703": 115, "21704": 118, "21705": 115,
    "21710": 110, "21716": 108, "21718": 110, "21740": 108, "21787": 110,
    
    # VIRGINIA
    # Northern Virginia / DC Metro (High COLI - 125-145)
    "22003": 140, "22015": 135, "22030": 138, "22031": 140, "22032": 135,
    "22041": 135, "22042": 138, "22043": 140, "22044": 135, "22046": 142,
    "22060": 132, "22066": 130, "22101": 140, "22102": 145, "22124": 138,
    "22150": 130, "22151": 128, "22152": 130, "22153": 125, "22180": 142,
    "22181": 145, "22182": 148, "22183": 140, "22201": 138, "22202": 135,
    "22203": 140, "22204": 135, "22205": 142, "22206": 130, "22207": 145,
    "22213": 132, "22301": 135, "22302": 138, "22304": 130, "22305": 132,
    "22314": 140, "22315": 138,
    
    # Fairfax County, VA (High COLI - 130-145)
    "20120": 135, "20121": 138, "20124": 135, "20151": 140, "20152": 135,
    "20170": 132, "20171": 135, "20175": 130, "20190": 132, "20191": 135,
    "20194": 138, "22003": 140, "22009": 138, "22015": 135, "22027": 142,
    "22030": 138, "22031": 140, "22032": 135, "22033": 138, "22035": 135,
    "22039": 140, "22042": 138, "22043": 140, "22060": 132, "22066": 130,
    "22079": 145, "22081": 140, "22092": 142, "22095": 138,
    
    # Richmond Metro Area (Moderate COLI - 105-118)
    "23173": 110, "23223": 108, "23224": 105, "23225": 108, "23226": 115,
    "23227": 105, "23230": 118, "23233": 112, "23235": 115, "23236": 112,
    "23294": 110, "23059": 108, "23060": 110, "23061": 112, "23113": 105,
    "23114": 108, "23120": 105, "23229": 110, "23238": 115, "23832": 105,
    "23834": 108, "23838": 105,
    
    # Virginia Beach/Norfolk Area (Moderate COLI - 105-115)
    "23451": 115, "23452": 112, "23453": 110, "23454": 112, "23455": 108,
    "23456": 110, "23457": 115, "23462": 112, "23464": 108, "23502": 108,
    "23503": 105, "23504": 108, "23505": 110, "23507": 105, "23508": 108,
    "23509": 110, "23510": 105, "23511": 108, "23513": 105, "23518": 108,
    "23551": 105, "23601": 108, "23602": 105, "23603": 108, "23604": 110,
    "23606": 108, "23608": 105, "23669": 108,
    
    # Charlottesville Area (Moderate COLI - 108-115)
    "22901": 115, "22902": 112, "22903": 115, "22904": 110, "22911": 108,
    "22936": 110, "22940": 108, "22980": 110,
    
    # Roanoke Area (Lower-Moderate COLI - 98-108)
    "24012": 105, "24013": 102, "24014": 105, "24015": 108, "24016": 105,
    "24017": 102, "24018": 100, "24019": 98, "24153": 100, "24179": 102,
    "24201": 100, "24210": 98, "24234": 100,
    
    # MINNESOTA
    # Twin Cities Metro (Minneapolis-St. Paul) (Moderate-High COLI - 108-125)
    # Minneapolis
    "55401": 120, "55402": 118, "55403": 115, "55404": 112, "55405": 108,
    "55406": 110, "55407": 108, "55408": 105, "55409": 108, "55410": 112,
    "55411": 105, "55412": 108, "55413": 110, "55414": 115, "55415": 118,
    "55416": 122, "55417": 115, "55418": 110, "55419": 112, "55420": 115,
    "55421": 108, "55422": 110, "55423": 105, "55424": 112, "55425": 115,
    "55426": 118, "55427": 110, "55428": 108, "55429": 105, "55430": 108,
    "55431": 110, "55432": 105, "55433": 108, "55434": 110, "55435": 112,
    "55436": 115, "55437": 112, "55438": 108, "55439": 110, "55441": 112,
    "55443": 108, "55444": 105, "55445": 108, "55446": 110, "55447": 105,
    "55448": 108,
    
    # St. Paul
    "55101": 115, "55102": 118, "55103": 112, "55104": 115, "55105": 118,
    "55106": 108, "55107": 105, "55108": 108, "55109": 110, "55110": 112,
    "55112": 108, "55113": 110, "55116": 115, "55117": 110, "55118": 108,
    "55119": 105, "55120": 108, "55123": 110, "55124": 112, "55125": 110,
    "55126": 108, "55127": 105, "55128": 108, "55129": 110, "55130": 105,
    "55133": 108, "55144": 110, "55155": 108, "55161": 110, "55164": 105,
    "55165": 108, "55166": 110, "55167": 108, "55168": 105, "55169": 108,
    "55172": 110, "55175": 108, "55176": 105, "55177": 108, "55182": 110,
    "55187": 108, "55188": 105, "55191": 108,
    
    # Western Metro Suburbs (Higher COLI - 115-125)
    "55305": 122, "55317": 118, "55318": 115, "55322": 120, "55331": 118,
    "55337": 115, "55343": 125, "55345": 122, "55347": 118, "55356": 120,
    "55357": 118, "55359": 115, "55361": 118, "55364": 115, "55391": 120,
    "55441": 115, "55442": 118,
    
    # Eastern Metro Suburbs (Moderate COLI - 110-118)
    "55014": 115, "55042": 112, "55055": 115, "55071": 112, "55082": 118,
    "55090": 115, "55092": 112, "55115": 110, "55121": 115, "55122": 118,
    "55150": 112, "55306": 115, "55340": 112, "55372": 115, "55378": 112,
    "55379": 115, "55381": 112, "55382": 115, "55386": 112, "55387": 115,
    "55388": 112, "55390": 115,
    
    # Duluth Area (Lower-Moderate COLI - 100-108)
    "55802": 105, "55803": 108, "55804": 105, "55805": 102, "55806": 105,
    "55807": 108, "55808": 105, "55810": 102, "55811": 105, "55812": 100,
    
    # Rochester Area (Moderate COLI - 105-112)
    "55901": 110, "55902": 108, "55904": 112, "55905": 110, "55906": 108,
    "55909": 105,
    
    # St. Cloud Area (Lower-Moderate COLI - 98-105)
    "56301": 105, "56303": 102, "56304": 100, "56321": 98, "56374": 100,
    
    # Mankato Area (Lower-Moderate COLI - 98-105)
    "56001": 102, "56002": 100, "56003": 105, "56006": 98, "56019": 100,
    
    # Default fallback for unknown zip codes
    "default": 115
}

def get_coli_by_zip(zip_code: str) -> float:
    """Get Cost of Living Index by zip code for MN, VA, DC, MD"""
    # Remove any extensions (e.g., "12345-6789" -> "12345")
    zip_5 = zip_code.split('-')[0][:5]
    
    # Direct lookup
    if zip_5 in COLI_DATA:
        return COLI_DATA[zip_5]
    
    # State-based fallback using zip code prefixes
    zip_prefix_2 = zip_5[:2]
    zip_prefix_3 = zip_5[:3]
    
    # State averages based on zip code prefixes
    state_averages = {
        # Washington DC (200xx)
        "20": 135,
        
        # Maryland (206xx-212xx)
        "21": 115,  # Most of Maryland
        "207": 118,  # Southern MD
        "208": 125,  # Montgomery County area
        "209": 130,  # Upper Montgomery County
        
        # Virginia (220xx-246xx)
        "22": 130,  # Northern VA (high COLI)
        "23": 110,  # Central/Eastern VA
        "24": 102,  # Western/Southwest VA
        "232": 108,  # Richmond area
        "234": 110,  # Norfolk/Virginia Beach area
        "229": 115,  # Charlottesville area
        
        # Minnesota (550xx-567xx)
        "55": 110,  # Twin Cities area
        "556": 100,  # Greater Minnesota
        "557": 98,   # Northern Minnesota
        "550": 115,  # Minneapolis core
        "551": 112,  # St. Paul core
    }
    
    # Try 3-digit prefix first (more specific)
    if zip_prefix_3 in state_averages:
        return state_averages[zip_prefix_3]
    
    # Fall back to 2-digit prefix
    if zip_prefix_2 in state_averages:
        return state_averages[zip_prefix_2]
    
    # Final fallback
    return COLI_DATA["default"]

def calculate_labor_hours(request: QuoteRequest) -> float:
    """Calculate total labor hours based on property features"""
    hours = 0.0
    
    # Base room calculations - use both beds and bedrooms (take max)
    total_bedrooms = max(request.beds, request.bedrooms)
    hours += total_bedrooms * 0.3  # 0.3 hours per bedroom
    hours += request.full_bathrooms * 0.5  # 0.75 hours per full bathroom
    hours += request.half_bathrooms * 0.25  # 0.25 hours per half bathroom
    hours += request.living_rooms * 0.3  # 0.5 hours per living room
    hours += request.kitchens * 0.6 # 1 hour per kitchen
    
    # Square footage calculations
    hours += request.carpet_area * 0.0003  # Carpet cleaning time
    hours += request.hard_floors_area * 0.0004  # Hard floor cleaning time
    
    # Laundry time (always included)
    hours += 0.5  # Base laundry time
    
    # Extra spaces (estimate 0.25 hours each)
    hours += request.extra_spaces * 0.20
    
    # Exterior features (estimate 0.25 hours each)  
    hours += request.exterior_features * 0.20
    
    # Pet multiplier (20% increase)
    if request.pets_allowed:
        hours *= 1.1
    
    return round(hours, 2)

def calculate_quote(request: QuoteRequest) -> QuoteBreakdown:
    """Calculate the full quote with all adjustments"""
    # Constants
    BASE_HOURLY_RATE = 25.0
    PROFIT_MARGIN_PCT = 0.25
    FLAT_FEE = 25.0
    MAX_HOURS_PER_CLEANER = 4.0
    PET_MULTIPLIER = 1.1
    
    # Calculate labor hours
    labor_hours = calculate_labor_hours(request)
    
    # Check if pet multiplier was applied
    pet_multiplier_applied = request.pets_allowed
    
    # Get COLI adjustment
    coli_index = get_coli_by_zip(request.zip_code)
    adjusted_hourly_rate = BASE_HOURLY_RATE * (coli_index / 100)
    
    # Calculate required cleaners (max 4 hours per cleaner)
    required_cleaners = math.ceil(labor_hours / MAX_HOURS_PER_CLEANER)
    
    # Calculate estimated actual time (NEW KPI)
    estimated_actual_time = round(labor_hours / required_cleaners, 2)
    
    # Calculate costs
    raw_cost = labor_hours * adjusted_hourly_rate
    profit_amount = raw_cost * PROFIT_MARGIN_PCT
    final_quote = raw_cost + profit_amount + FLAT_FEE
    
    return QuoteBreakdown(
        labor_hours=labor_hours,
        required_cleaners=required_cleaners,
        estimated_actual_time=estimated_actual_time,
        base_hourly_rate=BASE_HOURLY_RATE,
        coli_index=coli_index,
        adjusted_hourly_rate=round(adjusted_hourly_rate, 2),
        raw_cost=round(raw_cost, 2),
        profit_margin_percentage=PROFIT_MARGIN_PCT,
        profit_margin_amount=round(profit_amount, 2),
        flat_fee=FLAT_FEE,
        final_quote=round(final_quote, 2),
        max_hours_per_cleaner=MAX_HOURS_PER_CLEANER,
        pet_multiplier_applied=pet_multiplier_applied,
        pet_multiplier_rate=PET_MULTIPLIER
    )

async def save_quote_to_db(request: QuoteRequest, breakdown: QuoteBreakdown) -> str:
    """Save quote data to Supabase database - UPDATED to match frontend fields"""
    if not supabase:
        logger.warning("Supabase not initialized, skipping database save")
        return "db_skip"
    
    try:
        data = {
            # Contact Information - UPDATED to match frontend
            "full_name": request.full_name,
            "email": request.email,
            
            # Property Address Information - UPDATED to match frontend
            "address": request.address,
            "city": request.city,
            "state": request.state,
            "zip_code": request.zip_code,
            
            # Property Details - UPDATED to match frontend exactly
            "beds": request.beds,
            "bedrooms": request.bedrooms,
            "full_bathrooms": request.full_bathrooms,
            "half_bathrooms": request.half_bathrooms,
            "living_rooms": request.living_rooms,
            "kitchens": request.kitchens,
            "carpet_area": request.carpet_area,
            "hard_floors_area": request.hard_floors_area,
            "exterior_features": request.exterior_features,
            "extra_spaces": request.extra_spaces,
            "pets_allowed": request.pets_allowed,
            
            # Quote Breakdown - ALL calculation details stored
            "labor_hours": breakdown.labor_hours,
            "estimated_actual_time": breakdown.estimated_actual_time,
            "required_cleaners": breakdown.required_cleaners,
            "base_hourly_rate": breakdown.base_hourly_rate,
            "coli_index": breakdown.coli_index,
            "adjusted_rate": breakdown.adjusted_hourly_rate,
            "raw_cost": breakdown.raw_cost,
            "profit_margin_percentage": breakdown.profit_margin_percentage,
            "profit_margin_amount": breakdown.profit_margin_amount,
            "flat_fee": breakdown.flat_fee,
            "final_quote": breakdown.final_quote,
            "max_hours_per_cleaner": breakdown.max_hours_per_cleaner,
            "pet_multiplier_applied": breakdown.pet_multiplier_applied,
            "pet_multiplier_rate": breakdown.pet_multiplier_rate,
            "created_at": datetime.utcnow().isoformat()
        }
        
        result = supabase.table("quotes").insert(data).execute()
        return result.data[0]["id"] if result.data else "unknown"
        
    except Exception as e:
        logger.error(f"Database save error: {e}")
        return "error"

async def send_quote_email(request: QuoteRequest, breakdown: QuoteBreakdown, quote_id: str):
    """Send simplified quote email to customer using Brevo HTTP API"""
    if not BREVO_API_KEY:
        logger.warning("Brevo API key not set, skipping email send")
        return
    
    try:
        # Extract first name for personalization
        first_name = request.full_name.split()[0] if request.full_name else "there"
        
        # Create location string
        location_parts = [request.city, request.state]
        location_str = ", ".join([part for part in location_parts if part])
        location_display = f" in {location_str}" if location_str else ""
        
        # HTML email content with fixed color consistency
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style type="text/css">
                /* Force light mode and override dark mode */
                @media (prefers-color-scheme: dark) {{
                    .email-container {{ background-color: #f8f9fa !important; color: #1a1a1a !important; }}
                    .main-card {{ background-color: #ffffff !important; color: #1a1a1a !important; }}
                    .header-section {{ background-color: #ffffff !important; color: #1a1a1a !important; }}
                    .text-primary {{ color: #1a1a1a !important; }}
                    .text-secondary {{ color: #4a5568 !important; }}
                    .text-muted {{ color: #6b7280 !important; }}
                }}
                
                /* Prevent email client overrides */
                * {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
                table {{ border-collapse: collapse !important; }}
                
                /* Responsive design */
                @media screen and (max-width: 600px) {{
                    .email-container {{ width: 95% !important; padding: 10px !important; }}
                    .main-card {{ border-radius: 8px !important; }}
                    .header-section {{ padding: 20px 15px !important; }}
                    .content-section {{ padding: 20px 15px !important; }}
                    .quote-section {{ padding: 20px !important; margin: 20px 0 !important; }}
                    .property-details {{ padding: 20px !important; margin: 20px 0 !important; }}
                    .why-choose {{ padding: 20px !important; margin: 20px 0 !important; }}
                    .footer-section {{ padding: 20px !important; }}
                }}
            </style>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; margin: 0; padding: 0; background-color: #f8f9fa !important; color-scheme: light !important;">
            
            <div class="email-container" style="max-width: 500px; margin: 0 auto; padding: 20px; background-color: #f8f9fa !important;">
                
                <div class="main-card" style="background-color: #ffffff !important; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); overflow: hidden;">
                    
                    <!-- Header Section with Logo -->
                    <div class="header-section" style="background-color: #ffffff !important; padding: 30px 25px 25px 25px; text-align: center; border-bottom: 1px solid #f0f0f0;">
                        <img src="https://cleankey-frontend.vercel.app/_next/static/media/logo.a2b0d8a5.png" 
                            alt="CleanKey Logo" 
                            style="max-width: 120px; height: auto; display: block; margin: 0 auto; background-color: transparent;">
                    </div>
                    
                    <!-- Main Content -->
                    <div class="content-section" style="padding: 30px 25px; background-color: #ffffff !important;">
                        
                        <h2 class="text-primary" style="color: #1a1a1a !important; margin-bottom: 20px; font-size: 24px; font-weight: 600;">Hello {first_name}!</h2>
                        
                        <p class="text-secondary" style="font-size: 16px; margin-bottom: 25px; color: #4a5568 !important;">
                            Thank you for your interest in our professional short-term rental cleaning services{location_display}!
                        </p>
                        
                        <!-- Quote Section -->
                        <div class="quote-section" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important; padding: 25px; border-radius: 10px; text-align: center; margin: 30px 0;">
                            <h3 style="color: #ffffff !important; font-size: 28px; margin: 0; font-weight: 700; text-shadow: 0 1px 3px rgba(0,0,0,0.1);">YOUR QUOTE: ${breakdown.final_quote}</h3>
                        </div>
                        
                        <!-- Property Details -->
                        <div class="property-details" style="background-color: #f8fafc !important; padding: 25px; border-radius: 10px; margin: 25px 0; border-left: 4px solid #10b981;">
                            <h4 class="text-primary" style="color: #1a1a1a !important; margin-bottom: 18px; font-size: 18px; font-weight: 600;">YOUR PROPERTY:</h4>
                            <div style="display: block;">
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Total bedrooms: <strong style="color: #1a1a1a !important;">{request.bedrooms}</strong></div>
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Full bathrooms: <strong style="color: #1a1a1a !important;">{request.full_bathrooms}</strong></div>
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Half bathrooms: <strong style="color: #1a1a1a !important;">{request.half_bathrooms}</strong></div>
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Living rooms: <strong style="color: #1a1a1a !important;">{request.living_rooms}</strong></div>
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Kitchens: <strong style="color: #1a1a1a !important;">{request.kitchens}</strong></div>
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Carpet area: <strong style="color: #1a1a1a !important;">{request.carpet_area} sq ft</strong></div>
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Hard floors: <strong style="color: #1a1a1a !important;">{request.hard_floors_area} sq ft</strong></div>
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Extra spaces: <strong style="color: #1a1a1a !important;">{request.extra_spaces}</strong></div>
                                <div style="padding: 6px 0; color: #4a5568 !important;">• Exterior features: <strong style="color: #1a1a1a !important;">{request.exterior_features}</strong></div>
                                {"<div style='padding: 6px 0; color: #10b981 !important;'>• <strong style='color: #10b981 !important;'>Pet-friendly cleaning included</strong></div>" if request.pets_allowed else ""}
                            </div>
                        </div>
                        
                        <!-- Why Choose CleanKey -->
                        <div class="why-choose" style="background-color: #ffffff !important; padding: 25px; border-radius: 10px; margin: 25px 0; border: 1px solid #e2e8f0;">
                            <h4 class="text-primary" style="color: #1a1a1a !important; margin-bottom: 20px; font-size: 18px; font-weight: 600;">WHY CHOOSE CLEANKEY:</h4>
                            <div style="display: block;">
                                <div style="margin-bottom: 15px;">
                                    <div style="display: block;">
                                        <span style="color: #10b981 !important; font-size: 18px; font-weight: bold;">✓</span>
                                        <strong style="color: #1a1a1a !important; margin-left: 8px;">Vetted & Insured Cleaners</strong>
                                    </div>
                                    <div style="color: #4a5568 !important; font-size: 14px; margin-top: 4px; margin-left: 26px;">All our cleaners are background-checked and fully insured for your peace of mind</div>
                                </div>
                                <div style="margin-bottom: 15px;">
                                    <div style="display: block;">
                                        <span style="color: #10b981 !important; font-size: 18px; font-weight: bold;">✓</span>
                                        <strong style="color: #1a1a1a !important; margin-left: 8px;">Quality Guarantee</strong>
                                    </div>
                                    <div style="color: #4a5568 !important; font-size: 14px; margin-top: 4px; margin-left: 26px;">Not satisfied? We'll return within 24 hours to make it right, at no extra cost</div>
                                </div>
                                <div style="margin-bottom: 15px;">
                                    <div style="display: block;">
                                        <span style="color: #10b981 !important; font-size: 18px; font-weight: bold;">✓</span>
                                        <strong style="color: #1a1a1a !important; margin-left: 8px;">Transparent Pricing</strong>
                                    </div>
                                    <div style="color: #4a5568 !important; font-size: 14px; margin-top: 4px; margin-left: 26px;">No hidden fees or surprises - the price you see is exactly what you pay</div>
                                </div>
                                <div style="margin-bottom: 15px;">
                                    <div style="display: block;">
                                        <span style="color: #10b981 !important; font-size: 18px; font-weight: bold;">✓</span>
                                        <strong style="color: #1a1a1a !important; margin-left: 8px;">Flexible Scheduling</strong>
                                    </div>
                                    <div style="color: #4a5568 !important; font-size: 14px; margin-top: 4px; margin-left: 26px;">Book cleanings that work with your schedule, including same-day availability</div>
                                </div>
                                <div style="margin-bottom: 0;">
                                    <div style="display: block;">
                                        <span style="color: #10b981 !important; font-size: 18px; font-weight: bold;">✓</span>
                                        <strong style="color: #1a1a1a !important; margin-left: 8px;">Eco-Friendly Products</strong>
                                    </div>
                                    <div style="color: #4a5568 !important; font-size: 14px; margin-top: 4px; margin-left: 26px;">Safe, non-toxic cleaning supplies that protect your family and the environment</div>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Call to Action -->
                        <div style="text-align: center; margin: 35px 0;">
                            <p class="text-primary" style="font-size: 20px; margin-bottom: 25px; color: #1a1a1a !important; font-weight: 600;">Ready to book your professional cleaning?</p>
                            
                            <a href="{calendly_link}" 
                            style="display: inline-block; 
                                    background: linear-gradient(135deg, #1f2937 0%, #111827 100%) !important; 
                                    color: #ffffff !important; 
                                    padding: 16px 32px; 
                                    text-decoration: none; 
                                    border-radius: 8px; 
                                    font-size: 16px; 
                                    font-weight: 600;
                                    margin: 10px 0;
                                    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                                    border: none;
                                    cursor: pointer;">
                                TALK WITH OUR TEAM
                            </a>
                            
                            <p class="text-muted" style="font-size: 14px; color: #6b7280 !important; margin-top: 18px;">
                                Click the button above to choose a time that works best for you.
                            </p>
                        </div>
                        
                    </div>
                    
                    <!-- Footer -->
                    <div class="footer-section" style="background-color: #f8fafc !important; text-align: center; padding: 25px; border-top: 1px solid #e2e8f0;">
                        <p style="margin: 5px 0; color: #4a5568 !important;">Best regards,</p>
                        <p style="margin: 5px 0; font-weight: 600; color: #1a1a1a !important; font-size: 16px;">CleanKey Team</p>
                    </div>
                    
                </div>
                
            </div>
        </body>
        </html>
                """

        # Brevo API request
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json"
        }
        
        data = {
            "sender": {
                "name": "Clean Key",
                "email": COMPANY_EMAIL
            },
            "to": [{"email": request.email, "name": request.full_name}],
            "subject": "Your Short-Term Rental Cleaning Quote",
            "htmlContent": html_content
        }
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 201:
            logger.info(f"Quote email sent successfully to {request.email}")
        else:
            logger.error(f"Email send failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"Email send error: {e}")

    """Send simplified quote email to customer using Brevo HTTP API"""
    if not BREVO_API_KEY:
        logger.warning("Brevo API key not set, skipping email send")
        return
    
    try:
        # Extract first name for personalization
        first_name = request.full_name.split()[0] if request.full_name else "there"
        
        # Create location string
        location_parts = [request.city, request.state]
        location_str = ", ".join([part for part in location_parts if part])
        location_display = f" in {location_str}" if location_str else ""
        
        # HTML email content matching CleanKey website aesthetic
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 500px; margin: 0 auto; padding: 20px; background-color: #f8f9fa;">
            
            <div style="background-color: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); overflow: hidden;">
                
                <!-- Header Section with Logo -->
                <div style="background-color: #FCFBF8; padding: 30px 25px 25px 25px; text-align: center; border-bottom: 1px solid #f0f0f0;">
                    <img src="https://cleankey-frontend.vercel.app/_next/static/media/logo.a2b0d8a5.png" 
                        alt="CleanKey Logo" 
                        style="max-width: 120px; height: auto;">
                </div>
                
                <!-- Main Content -->
                <div style="padding: 30px 25px;">
                    
                    <h2 style="color: #1a1a1a; margin-bottom: 20px; font-size: 24px; font-weight: 600;">Hello {first_name}!</h2>
                    
                    <p style="font-size: 16px; margin-bottom: 25px; color: #4a5568;">
                        Thank you for your interest in our professional short-term rental cleaning services{location_display}!
                    </p>
                    
                    <!-- Quote Section -->
                    <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); padding: 25px; border-radius: 10px; text-align: center; margin: 30px 0;">
                        <h3 style="color: white; font-size: 28px; margin: 0; font-weight: 700; text-shadow: 0 1px 3px rgba(0,0,0,0.1);">YOUR QUOTE: ${breakdown.final_quote}</h3>
                    </div>
                    
                    <!-- Property Details -->
                    <div style="background-color: #f8fafc; padding: 25px; border-radius: 10px; margin: 25px 0; border-left: 4px solid #10b981;">
                        <h4 style="color: #1a1a1a; margin-bottom: 18px; font-size: 18px; font-weight: 600;">YOUR PROPERTY:</h4>
                        <div style="display: grid; gap: 8px;">
                            <div style="padding: 6px 0; color: #4a5568;">• Total bedrooms: <strong style="color: #1a1a1a;">{max(request.beds, request.bedrooms)}</strong></div>
                            <div style="padding: 6px 0; color: #4a5568;">• Full bathrooms: <strong style="color: #1a1a1a;">{request.full_bathrooms}</strong></div>
                            <div style="padding: 6px 0; color: #4a5568;">• Half bathrooms: <strong style="color: #1a1a1a;">{request.half_bathrooms}</strong></div>
                            <div style="padding: 6px 0; color: #4a5568;">• Living rooms: <strong style="color: #1a1a1a;">{request.living_rooms}</strong></div>
                            <div style="padding: 6px 0; color: #4a5568;">• Kitchens: <strong style="color: #1a1a1a;">{request.kitchens}</strong></div>
                            <div style="padding: 6px 0; color: #4a5568;">• Carpet area: <strong style="color: #1a1a1a;">{request.carpet_area} sq ft</strong></div>
                            <div style="padding: 6px 0; color: #4a5568;">• Hard floors: <strong style="color: #1a1a1a;">{request.hard_floors_area} sq ft</strong></div>
                            <div style="padding: 6px 0; color: #4a5568;">• Extra spaces: <strong style="color: #1a1a1a;">{request.extra_spaces}</strong></div>
                            <div style="padding: 6px 0; color: #4a5568;">• Exterior features: <strong style="color: #1a1a1a;">{request.exterior_features}</strong></div>
                            {"<div style='padding: 6px 0; color: #10b981;'>• <strong>Pet-friendly cleaning included</strong></div>" if request.pets_allowed else ""}
                        </div>
                    </div>
                    
                    <!-- Why Choose CleanKey -->
                    <div style="background-color: #fefefe; padding: 25px; border-radius: 10px; margin: 25px 0; border: 1px solid #e2e8f0;">
                        <h4 style="color: #1a1a1a; margin-bottom: 20px; font-size: 18px; font-weight: 600;">WHY CHOOSE CLEANKEY:</h4>
                        <div style="display: grid; gap: 15px;">
                            <div style="display: flex; align-items: flex-start; gap: 12px;">
                                <span style="color: #10b981; font-size: 18px; font-weight: bold; margin-top: 2px;">✓</span>
                                <div>
                                    <strong style="color: #1a1a1a;">Vetted & Insured Cleaners</strong>
                                    <div style="color: #4a5568; font-size: 14px; margin-top: 2px;">All our cleaners are background-checked and fully insured for your peace of mind</div>
                                </div>
                            </div>
                            <div style="display: flex; align-items: flex-start; gap: 12px;">
                                <span style="color: #10b981; font-size: 18px; font-weight: bold; margin-top: 2px;">✓</span>
                                <div>
                                    <strong style="color: #1a1a1a;">Quality Guarantee</strong>
                                    <div style="color: #4a5568; font-size: 14px; margin-top: 2px;">Not satisfied? We'll return within 24 hours to make it right, at no extra cost</div>
                                </div>
                            </div>
                            <div style="display: flex; align-items: flex-start; gap: 12px;">
                                <span style="color: #10b981; font-size: 18px; font-weight: bold; margin-top: 2px;">✓</span>
                                <div>
                                    <strong style="color: #1a1a1a;">Transparent Pricing</strong>
                                    <div style="color: #4a5568; font-size: 14px; margin-top: 2px;">No hidden fees or surprises - the price you see is exactly what you pay</div>
                                </div>
                            </div>
                            <div style="display: flex; align-items: flex-start; gap: 12px;">
                                <span style="color: #10b981; font-size: 18px; font-weight: bold; margin-top: 2px;">✓</span>
                                <div>
                                    <strong style="color: #1a1a1a;">Flexible Scheduling</strong>
                                    <div style="color: #4a5568; font-size: 14px; margin-top: 2px;">Book cleanings that work with your schedule, including same-day availability</div>
                                </div>
                            </div>
                            <div style="display: flex; align-items: flex-start; gap: 12px;">
                                <span style="color: #10b981; font-size: 18px; font-weight: bold; margin-top: 2px;">✓</span>
                                <div>
                                    <strong style="color: #1a1a1a;">Eco-Friendly Products</strong>
                                    <div style="color: #4a5568; font-size: 14px; margin-top: 2px;">Safe, non-toxic cleaning supplies that protect your family and the environment</div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Call to Action -->
                    <div style="text-align: center; margin: 35px 0;">
                        <p style="font-size: 20px; margin-bottom: 25px; color: #1a1a1a; font-weight: 600;">Ready to book your professional cleaning?</p>
                        
                        <a href="{calendly_link}" 
                        style="display: inline-block; 
                                background: linear-gradient(135deg, #1f2937 0%, #111827 100%); 
                                color: white !important; 
                                padding: 16px 32px; 
                                text-decoration: none; 
                                border-radius: 8px; 
                                font-size: 16px; 
                                font-weight: 600;
                                margin: 10px 0;
                                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                                transition: all 0.2s ease;">
                            TALK WITH OUR TEAM
                        </a>
                        
                        <p style="font-size: 14px; color: #6b7280; margin-top: 18px;">
                            Click the button above to choose a time that works best for you.
                        </p>
                    </div>
                    
                </div>
                
                <!-- Footer -->
                <div style="background-color: #f8fafc; text-align: center; padding: 25px; border-top: 1px solid #e2e8f0;">
                    <p style="margin: 5px 0; color: #4a5568;">Best regards,</p>
                    <p style="margin: 5px 0; font-weight: 600; color: #1a1a1a; font-size: 16px;">CleanKey Team</p>
                </div>
                
            </div>
        </body>
        </html>
                """

        # Brevo API request
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json"
        }
        
        data = {
            "sender": {
                "name": "CleanKey",
                "email": COMPANY_EMAIL
            },
            "to": [{"email": request.email, "name": request.full_name}],
            "subject": "Your Short-Term Rental Cleaning Quote",
            "htmlContent": html_content
        }
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 201:
            logger.info(f"Quote email sent successfully to {request.email}")
        else:
            logger.error(f"Email send failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"Email send error: {e}")

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Cleaning Quote API is running"}

@app.post("/api/quote", response_model=QuoteResponse)
async def create_quote(request: QuoteRequest, background_tasks: BackgroundTasks):
    """
    Calculate cleaning quote and send email
    """
    try:
        # Calculate the quote
        breakdown = calculate_quote(request)
        
        # Save to database (background task)
        quote_id = await save_quote_to_db(request, breakdown)
        
        # Send email (background task)
        background_tasks.add_task(send_quote_email, request, breakdown, quote_id)
        
        return QuoteResponse(
            quote=breakdown.final_quote,
            breakdown=breakdown,
            message=f"Quote calculated successfully! Check your email ({request.email}) for details."
        )
        
    except Exception as e:
        logger.error(f"Quote calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"Quote calculation failed: {str(e)}")

@app.get("/api/quotes")
async def get_quotes(limit: int = 50):
    """Get recent quotes (admin endpoint)"""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        result = supabase.table("quotes").select("*").order("created_at", desc=True).limit(limit).execute()
        return {"quotes": result.data}
    except Exception as e:
        logger.error(f"Failed to fetch quotes: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch quotes")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)