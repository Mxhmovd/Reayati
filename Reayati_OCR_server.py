from flask import Flask, request, jsonify
import logging
import os
import pytesseract
from PIL import Image, ImageFilter
from tqdm import tqdm  
from pdf2image import convert_from_path
import base64
import uuid
import re
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import NameObject, TextStringObject


pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MIME_EXT_MAP = {
    'application/pdf': '.pdf',
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/tiff': '.tiff',
    'image/gif': '.gif',
    'text/plain': '.txt',
    'application/zip': '.zip',
}


MAGIC_NUMBERS = {
    b'\x25\x50\x44\x46': '.pdf',                   
    b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A': '.png',  
    b'\xFF\xD8\xFF': '.jpg',                       
    b'\x49\x49\x2A\x00': '.tiff',                  
    b'\x4D\x4D\x00\x2A': '.tiff',                  
    b'\x47\x49\x46\x38': '.gif',                   
    b'\x50\x4B\x03\x04': '.zip',                   
}


def decode_b64_file(b64_data, dest_dir='decoded_files', fname=None):
    try:
        
        uri_pattern = re.compile(r'data:(?P<mime>[\w/-]+);base64,(?P<data>.+)')

        uri_match = uri_pattern.match(b64_data)
        if uri_match:
            mime = uri_match.group('mime')
            b64_str = uri_match.group('data')
            ext = MIME_EXT_MAP.get(mime)
            if not ext:
                raise ValueError(f"Unsupported MIME type: {mime}")
        else:
            b64_str = b64_data

        
        raw_data = base64.b64decode(b64_str)

        
        if not uri_match:
            ext = None
            for sig, file_ext in MAGIC_NUMBERS.items():
                if raw_data.startswith(sig):
                    ext = file_ext
                    break
            if not ext:
                
                ext = ".pdf"

        
        if not fname:
            uid = uuid.uuid4().hex
            fname = f"decoded_file_{uid}"

        
        os.makedirs(dest_dir, exist_ok=True)

        
        fpath = os.path.join(dest_dir, f"{fname}{ext}")
        with open(fpath, 'wb') as f:
            f.write(raw_data)

        print(f"Decoded file saved at: {fpath}")

        
        if ext == ".pdf":
            fixed_path = os.path.join(dest_dir, f"repaired_{fname}{ext}")
            fixed_path = repair_pdf_meta(fpath, fixed_path)
            return fixed_path

        return fpath

    except Exception as ex:
        raise ValueError(f"Failed to decode Base64 data: {ex}")


def repair_pdf_meta(input_path, output_path):
    try:
        rdr = PdfReader(input_path)
        wrt = PdfWriter()

        
        for pg in rdr.pages:
            wrt.add_page(pg)

        
        meta = rdr.metadata or {}
        meta[NameObject("/MIMEType")] = TextStringObject("application/pdf")
        wrt.add_metadata(meta)

        
        with open(output_path, 'wb') as out_f:
            wrt.write(out_f)

        print(f"Repaired PDF saved with MIME metadata at: {output_path}")
        return output_path

    except Exception as ex:
        print(f"Error fixing metadata: {ex}")
        raise ValueError("Failed to fix metadata for the PDF.")


def enhance_img(img):
    img = img.convert('L')  
    img = img.filter(ImageFilter.SHARPEN)  
    return img


def extract_text_img(img_path, language='eng', save_file=False, out_path='ocr_output.txt'):
    try:
        img = Image.open(img_path)  
        enhanced = enhance_img(img)  
        txt = pytesseract.image_to_string(enhanced, lang=language)  
        if save_file:
            with open(out_path, 'w', encoding='utf-8') as out_f:
                out_f.write(txt)
            print(f"OCR output saved to {out_path}")
        return txt
    except Exception as ex:
        return f"Error processing {img_path}: {ex}"


def extract_text_pdf(fpath, language='eng', save_file=False, out_path='ocr_output.txt'):
    try:
        imgs = convert_from_path(fpath)  
        content = ""
        for idx, img in enumerate(imgs):
            enhanced = enhance_img(img)
            txt = pytesseract.image_to_string(enhanced, lang=language)
            content += f"--- Page {idx + 1} ---\n{txt}\n"
        if save_file:
            with open(out_path, 'w', encoding='utf-8') as out_f:
                out_f.write(content)
            print(f"OCR output saved to {out_path}")
        return content
    except Exception as ex:
        return f"Error processing PDF {fpath}: {ex}"


def extract_text_file(fpath, language='eng', save_file=False, out_path='ocr_output.txt'):
    result = ""
    if fpath.lower().endswith('.pdf'):
        result = extract_text_pdf(fpath, lang=language, save_file=save_file, out_path=out_path)
    elif fpath.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')):
        result = extract_text_img(fpath, lang=language, save_file=save_file, out_path=out_path)
    else:
        result = f"Unsupported file type: {fpath}"
    return result


def handle_b64_string(b64_data, language='eng', save_file=False, out_path='base64_ocr_output.txt'):
    try:
        
        fpath = decode_b64_file(b64_data)
        logger.info(f"Decoded file saved at: {fpath}")

        
        txt_output = extract_text_file(fpath, lang=language, save_file=save_file, out_path=out_path)
        logger.info("OCR completed successfully.")

        return txt_output
    except Exception as ex:
        logger.error(f"Error processing Base64 string: {ex}")
        raise




def get_patient_data(txt):
    """
    Extract minimal patient info from text: name, age, and sex/gender.
    """
    data = {"name": None, "age": None, "sex": None}

    name_rx = re.compile(r"Patient:\s*([A-Za-z ,.'-]+)", re.IGNORECASE)
    age_rx = re.compile(r"D\.O\.B:\s*\S+\s*-\s*(\d{1,2})\s*Years", re.IGNORECASE)
    sex_rx = re.compile(r"(?:Sex|Gender):\s*(Male|Female)", re.IGNORECASE)

    name_m = name_rx.search(txt)
    if name_m:
        data["name"] = name_m.group(1).strip()

    age_m = age_rx.search(txt)
    if age_m:
        data["age"] = age_m.group(1).strip()

    sex_m = sex_rx.search(txt)
    if sex_m:
        data["sex"] = sex_m.group(1).capitalize()

    return data




def get_creatinine_serum(ln):
    """
    Parses a string representing the Creatinine, Serum test result.
    e.g. "Creatinine, Serum 0.7 mg/dL 0.70 - 1.20"
    """
    rx = re.compile(
        r"Creatinine,\s*Serum\s+([\d.]+)\s+(\S+)\s+([\d.]+\s*-\s*[\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()
    ref_range = m.group(3).strip()

    
    min_val, max_val = map(float, ref_range.split('-'))

    
    if val < min_val:
        msg = (
            "The creatinine serum level is below the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )
    elif val > max_val:
        msg = (
            "The creatinine serum level is above the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )
    else:
        msg = (
            "The creatinine serum level is within the normal range."
        )

    return {
        "test_name": "Creatinine, Serum",
        "value": val,
        "unit": unit,
        "reference_range": ref_range,
        "min_ref_value": min_val,
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_alt(ln):
    """
    Parses a string representing the Alanine Amino Transferase (ALT/GPT) test result.
    e.g. "Alanine Amino Transferase (ALT/GPT), Serum 8 U/L Up To: 41"
    """
    rx = re.compile(
        r"Alanine Amino Transferase \(ALT/GPT\), Serum\s+([\d.]+)\s+(\S+)\s+Up To:\s*([\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()

    
    max_val = float(m.group(3).strip())
    min_val = 0  

    
    if min_val <= val <= max_val:
        msg = (
            "The Alanine Amino Transferase (ALT/GPT) level is within the safe range."
        )
    else:
        msg = (
            "The Alanine Amino Transferase (ALT/GPT) level is above the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Alanine Amino Transferase (ALT/GPT), Serum",
        "value": val,
        "unit": unit,
        "reference_range": f"Up To: {max_val}",
        "min_ref_value": min_val,
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_ast(ln):
    """
    Parses a string representing the Aspartate Amino Transferase (AST/GOT) test result.
    e.g. "* Aspartate Amino Transferase (AST/GOT), Serum 13 U/L Up To: 40"
    """
    rx = re.compile(
        r"\*?\s*Aspartate Amino Transferase \(AST/GOT\), Serum\s+([\d.]+)\s+(\S+)\s+Up To:\s*([\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()

    
    max_val = float(m.group(3).strip())
    min_val = 0  

    
    if min_val <= val <= max_val:
        msg = (
            "The Aspartate Amino Transferase (AST/GOT) level is within the safe range."
        )
    else:
        msg = (
            "The Aspartate Amino Transferase (AST/GOT) level is above the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Aspartate Amino Transferase (AST/GOT), Serum",
        "value": val,
        "unit": unit,
        "reference_range": f"Up To: {max_val}",
        "min_ref_value": min_val,
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_ck(ln):
    """
    Parses a string representing the Creatine Kinase (CPK) test result.
    e.g. "Creatine Kinase (CPK), Serum 23 U/L Up To: 170"
    """
    rx = re.compile(
        r"Creatine Kinase \(CPK\), Serum\s+([\d.]+)\s+(\S+)\s+Up To:\s*([\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()

    
    max_val = float(m.group(3).strip())
    min_val = 0  

    
    if min_val <= val <= max_val:
        msg = (
            "The Creatine Kinase (CPK) level is within the safe range."
        )
    else:
        msg = (
            "The Creatine Kinase (CPK) level is outside the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Creatine Kinase (CPK), Serum",
        "value": val,
        "unit": unit,
        "reference_range": f"Up To: {max_val}",
        "min_ref_value": min_val,
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_esr(ln):
    """
    Parses a string representing the ESR test result.
    e.g. "ESR 100 mm/1 hr 0- 15"
    """
    rx = re.compile(
        r"(?:ESR)\s+([\d.]+)\s+(mm/1\s*hr)\s+(.*)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()
    ref_range = m.group(3).strip()

    
    min_val, max_val = map(float, ref_range.replace('-', ' ').split())

    
    if min_val <= val <= max_val:
        msg = (
            "The ESR level is within the normal range."
        )
    elif val < min_val:
        msg = (
            "The ESR level is below the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )
    else:
        msg = (
            "The ESR level is above the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "ESR",
        "value": val,
        "unit": unit,
        "reference_range": ref_range,
        "min_ref_value": min_val,
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_rf(ln):
    """
    Parses a string representing the Rheumatoid Factor (RF) test result.
    e.g. "Rheumatoid Factor (RF), Titer, Serum 7.9 U/mL Negative: Less than 14.0"
    """
    rx = re.compile(
        r"Rheumatoid Factor \(RF\), Titer, Serum\s+([\d.]+)\s+(\S+)\s+Negative:\s*Less\s*than\s*([\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()
    max_val = float(m.group(3).strip())
    min_val = 0  

    
    if val < max_val:
        msg = (
            "The Rheumatoid Factor (RF) level is within the normal range (Negative)."
        )
    else:
        msg = (
            "The Rheumatoid Factor (RF) level is above the normal range (Positive). "
            "This may indicate the presence of RF in the blood. Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Rheumatoid Factor (RF), Titer, Serum",
        "value": val,
        "unit": unit,
        "reference_range": f"Negative: Less than {max_val}",
        "min_ref_value": min_val,
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_ana(ln):
    """
    Parses a string representing the Anti Nuclear Abs (ANA) test result.
    e.g. "Anti Nuclear Abs (ANA), Serum Less than 1:40 Negative: Less than 1:40"
    """
    rx = re.compile(
        r"Anti Nuclear Abs \(ANA\), Serum\s+(.+?)\s+Negative:\s*(.*)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = m.group(1).strip()
    neg_ref = m.group(2).strip()

    
    if val == neg_ref:
        msg = (
            "The Anti Nuclear Abs (ANA) level is within the normal range (Negative)."
        )
    else:
        msg = (
            "The Anti Nuclear Abs (ANA) level is outside the normal range (Positive). "
            "This may suggest the presence of ANA. Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Anti Nuclear Abs (ANA), Serum",
        "value": val,
        "unit": "",
        "reference_range": f"Negative: {neg_ref}",
        "display_message": msg
    }

def get_acl_igm(ln):
    """
    Parses a string representing the Anti Cardiolipin (ACL) IgM test result.
    e.g. "Anti Cardiolipin (ACL) IgM, Serum 3 MPL/mL Negative: < 12.0"
    """
    rx = re.compile(
        r"Anti Cardiolipin \(ACL\)\s*IgM,\s*Serum\s+([\d.]+)\s+(\S+)\s+Negative:\s*<\s*([\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()
    max_val = float(m.group(3).strip())

    
    if val < max_val:
        msg = (
            "The Anti Cardiolipin (ACL) IgM level is within the normal range (Negative)."
        )
    else:
        msg = (
            "The Anti Cardiolipin (ACL) IgM level is outside the normal range (Positive). "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Anti Cardiolipin (ACL) IgM, Serum",
        "value": val,
        "unit": unit,
        "reference_range": f"Negative: < {max_val}",
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_acl_igg(ln):
    """
    Parses a string representing the Anti Cardiolipin (ACL) IgG test result.
    e.g. "Anti Cardiolipin (ACL) IgG, Serum 10 GPL/mL Negative: < 12.0"
    """
    rx = re.compile(
        r"Anti Cardiolipin \(ACL\)\s*IgG,\s*Serum\s+([\d.]+)\s+(\S+)\s+Negative:\s*<\s*([\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()
    max_val = float(m.group(3).strip())

    
    if val < max_val:
        msg = (
            "The Anti Cardiolipin (ACL) IgG level is within the normal range (Negative)."
        )
    else:
        msg = (
            "The Anti Cardiolipin (ACL) IgG level is outside the normal range (Positive). "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Anti Cardiolipin (ACL) IgG, Serum",
        "value": val,
        "unit": unit,
        "reference_range": f"Negative: < {max_val}",
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_antiphos_igg(ln):
    """
    Parses a string representing the Anti Phospholipids IgG test result.
    e.g. "Anti Phospholipids IgG, Serum 4 Au/mL Negative: Less than 10"
    """
    rx = re.compile(
        r"Anti Phospholipids IgG,\s*Serum\s+([\d.]+)\s+(\S+)\s+Negative:\s*Less\s*than\s*([\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()
    max_val = float(m.group(3).strip())

    
    if val < max_val:
        msg = (
            "The Anti Phospholipids IgG level is within the normal range (Negative)."
        )
    else:
        msg = (
            "The Anti Phospholipids IgG level is outside the normal range (Positive). "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Anti Phospholipids IgG, Serum",
        "value": val,
        "unit": unit,
        "reference_range": f"Negative: Less than {max_val}",
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_antiphos_igm(ln):
    """
    Parses a string representing the Anti Phospholipids IgM test result.
    e.g. "Anti Phospholipids IgM, Serum 3 Au/mL Negative: Less than 10"
    """
    rx = re.compile(
        r"Anti Phospholipids IgM,\s*Serum\s+([\d.]+)\s+(\S+)\s+Negative:\s*Less\s*than\s*([\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()
    max_val = float(m.group(3).strip())

    
    if val < max_val:
        msg = (
            "The Anti Phospholipids IgM level is within the normal range (Negative)."
        )
    else:
        msg = (
            "The Anti Phospholipids IgM level is outside the normal range (Positive). "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": "Anti Phospholipids IgM, Serum",
        "value": val,
        "unit": unit,
        "reference_range": f"Negative: Less than {max_val}",
        "max_ref_value": max_val,
        "display_message": msg
    }

def get_lupus_anticoagulant(ln):
    """
    Parses a string representing the Lupus Anticoagulant test result.
    e.g. "Lupus Anticoagulant, Citrated Plasma 38.4 Sec 31.0 - 44.0"
    """
    rx = re.compile(
        r"Lupus Anticoagulant,\s*Citrated Plasma\s+([\d.]+)\s+(\S+)\s+([\d.]+\s*-\s*[\d.]+)",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    val = float(m.group(1).strip())
    unit = m.group(2).strip()
    ref_range = m.group(3).strip()

    
    min_val, max_val = map(float, ref_range.split('-'))

    
    if val < min_val:
        msg = (
            "The Lupus Anticoagulant level is below the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )
    elif val > max_val:
        msg = (
            "The Lupus Anticoagulant level is above the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )
    else:
        msg = (
            "The Lupus Anticoagulant level is within the normal range."
        )

    return {
        "test_name": "Lupus Anticoagulant, Citrated Plasma",
        "value": val,
        "unit": unit,
        "reference_range": ref_range,
        "min_ref_value": min_val,
        "max_ref_value": max_val,
        "display_message": msg
    }





def get_anticcp_igg_block(lines_blk):
    """
    Handle multi-line Anti CCP IgG test.
    Now also includes a 'display_message' by comparing 'value'
    to negative, equivocal, and positive thresholds.
    """
    
    filtered = []
    for ln in lines_blk:
        lower_ln = ln.lower()
        if "printed on:" in lower_ln:
            continue
        if "release date" in lower_ln:
            continue
        if "page" in lower_ln:
            continue
        filtered.append(ln.strip())

    combined = " ".join(filtered)
    

    
    main_rx = re.compile(
        r"Anti CCP IgG \(Cyclic Citrullinated Peptide\), Serum\s+([\d.]+)\s+(\S+)\s+(.*)",
        re.IGNORECASE
    )
    main_m = main_rx.search(combined)
    if not main_m:
        return None

    test_val_str = main_m.group(1).strip()
    test_unit = main_m.group(2).strip()
    raw_ref = main_m.group(3).strip()

    
    
    
    
    lab_idx = raw_ref.lower().find("lab director")
    if lab_idx != -1:
        raw_ref = raw_ref[:lab_idx].strip()

    
    
    ranges_rx = re.compile(
        r"Negative:\s*Less\s*than\s*([\d.]+)\s+Equivocal:\s*([\d.]+)\s*-\s*([\d.]+)\s+Positive:\s*More\s*than\s*([\d.]+)",
        re.IGNORECASE
    )
    ranges_m = ranges_rx.search(raw_ref)

    
    neg_val = None
    equiv_start = None
    equiv_end = None
    pos_val = None
    msg = "Could not parse reference range; please consult a healthcare provider."

    
    if ranges_m:
        neg_val = ranges_m.group(1).strip()
        equiv_start = ranges_m.group(2).strip()
        equiv_end = ranges_m.group(3).strip()
        pos_val = ranges_m.group(4).strip()

        try:
            test_val_f = float(test_val_str)
            neg_val_f = float(neg_val)
            equiv_start_f = float(equiv_start)
            equiv_end_f = float(equiv_end)
            pos_val_f = float(pos_val)

            
            if test_val_f < neg_val_f:
                msg = (
                    "The Anti CCP IgG level is NEGATIVE based on the reference range."
                )
            elif test_val_f <= equiv_end_f:
                msg = (
                    "The Anti CCP IgG level is EQUIVOCAL based on the reference range."
                )
            else:
                msg = (
                    "The Anti CCP IgG level is POSITIVE based on the reference range."
                )

        except ValueError:
            
            pass

    
    return {
        "test_name": "Anti CCP IgG (Cyclic Citrullinated Peptide), Serum",
        "value": test_val_str,  
        "unit": test_unit,
        "reference_range": raw_ref,  
        "negative_value": neg_val,
        "equivocal_range": (
            f"{equiv_start} - {equiv_end}" if equiv_start and equiv_end else None
        ),
        "positive_value": pos_val,
        "display_message": msg
    }




def get_c_anca_serum(ln):
    """
    Parses a string representing the (c-ANCA), Serum test result.
    e.g. "(c-ANCA), Serum"
    """
    rx = re.compile(r"^\(c-anca\),\s*serum\s*$", re.IGNORECASE)
    m = rx.search(ln)
    if not m:
        return None

    
    msg = (
        "The (c-ANCA), Serum test result does not include value, unit, or reference range. "
        "Please refer to the detailed report or consult a healthcare provider for interpretation."
    )

    return {
        "test_name": "(c-ANCA), Serum",
        "value": None,
        "unit": None,
        "reference_range": None,
        "display_message": msg
    }

def get_p_anca_line(ln):
    """
    Parses a string representing the P-ANCA test result.
    e.g. "P-ANCA Less than 1/10 Less than 1/10"
    """
    rx = re.compile(
        r"^(P-ANCA)\s+(Less than [\d./]+)\s+(Less than [\d./]+)$",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    test_nm = m.group(1).upper()  
    val = m.group(2).strip()
    ref_range = m.group(3).strip()

    
    if val == ref_range:
        msg = (
            "The P-ANCA test result is within the normal range."
        )
    else:
        msg = (
            "The P-ANCA test result is outside the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": test_nm,
        "value": val,
        "unit": None,
        "reference_range": ref_range,
        "display_message": msg
    }

def get_c_anca_line(ln):
    """
    Parses a string representing the C-ANCA test result.
    e.g. "C-ANCA Less than 1/10 Less than 1/10"
    """
    rx = re.compile(
        r"^(C-ANCA)\s+(Less than [\d./]+)\s+(Less than [\d./]+)$",
        re.IGNORECASE
    )
    m = rx.search(ln)
    if not m:
        return None

    test_nm = m.group(1).upper()  
    val = m.group(2).strip()
    ref_range = m.group(3).strip()

    
    if val == ref_range:
        msg = (
            "The C-ANCA test result is within the normal range."
        )
    else:
        msg = (
            "The C-ANCA test result is outside the normal range. "
            "Please consult a healthcare provider for further evaluation."
        )

    return {
        "test_name": test_nm,
        "value": val,
        "unit": None,
        "reference_range": ref_range,
        "display_message": msg
    }




SINGLE_LINE_PARSERS = {
    "Creatinine, Serum": get_creatinine_serum,
    "Alanine Amino Transferase (ALT/GPT), Serum": get_alt,
    "Aspartate Amino Transferase (AST/GOT), Serum": get_ast,
    "Creatine Kinase (CPK), Serum": get_ck,
    "ESR": get_esr,
    "Rheumatoid Factor (RF), Titer, Serum": get_rf,
    "Anti Nuclear Abs (ANA), Serum": get_ana,
    "Anti Cardiolipin (ACL) IgM, Serum": get_acl_igm,
    "Anti Cardiolipin (ACL) IgG, Serum": get_acl_igg,
    "Anti Phospholipids IgG, Serum": get_antiphos_igg,
    "Anti Phospholipids IgM, Serum": get_antiphos_igm,
    "Lupus Anticoagulant, Citrated Plasma": get_lupus_anticoagulant,

    
    "(c-ANCA), Serum": get_c_anca_serum,
    "P-ANCA": get_p_anca_line,
    "C-ANCA": get_c_anca_line,
}

MULTI_LINE_PARSERS = {
    
    "Anti CCP IgG (Cyclic Citrullinated Peptide), Serum": get_anticcp_igg_block,
}




def locate_test_lines(txt, test_substr):
    """
    Return all lines that contain test_substr (case-insensitive).
    We assume each test is fully on that single line.
    """
    results = []
    lines = txt.splitlines()
    for ln in lines:
        if test_substr.lower() in ln.lower():
            results.append(ln.strip())
    return results

def locate_test_block(txt, test_substr, blk_size=11):
    """
    For multi-line tests:
    When we find a line containing test_substr,
    we also grab the next 'blk_size' lines to parse them together.
    """
    result_blks = []
    lines = txt.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        ln = lines[i].strip()
        if test_substr.lower() in ln.lower():
            blk = [ln]
            for j in range(1, blk_size+1):
                if i+j < n:
                    blk.append(lines[i+j].strip())
            result_blks.append(blk)
            i += (blk_size + 1)
        else:
            i += 1
    return result_blks




def analyze_test_data(txt):
    """
    1) Extract patient info
    2) Parse single-line tests
    3) Parse multi-line tests (Anti CCP IgG)
    """
    patient_data = get_patient_data(txt)
    final_results = []

    
    for test_substr, parser_fn in SINGLE_LINE_PARSERS.items():
        matched_lns = locate_test_lines(txt, test_substr)
        for ml in matched_lns:
            parsed = parser_fn(ml)
            if parsed:
                final_results.append(parsed)

    
    for test_substr, blk_parser_fn in MULTI_LINE_PARSERS.items():
        blks = locate_test_block(txt, test_substr, blk_size=11)
        for blk in blks:
            parsed = blk_parser_fn(blk)
            if parsed:
                final_results.append(parsed)

    return patient_data, final_results

def main(b64_str):
    try:
        
        fpath = decode_b64_file(b64_str)

        
        if fpath.lower().endswith('.pdf'):
            ocr_res = extract_text_pdf(fpath)
        elif fpath.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')):
            ocr_res = extract_text_img(fpath)
        else:
            raise ValueError(f"Unsupported file type for OCR: {fpath}")

        
        patient_data, test_data = analyze_test_data(ocr_res)

        
        print("===== Patient Information =====")
        print(patient_data)

        print("\n===== Test Results =====")
        for res in test_data:
            print(res)

    except Exception as ex:
        print(f"An error occurred: {ex}")


app = Flask(__name__)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.route('/process_base64', methods=['POST'])
def process_base64():
    """
    Endpoint to process Base64 encoded files.
    """
    try:
        
        req_data = request.json
        b64_str = req_data.get('base64_string')
        language = req_data.get('lang', 'eng')  

        if not b64_str:
            return jsonify({"error": "Base64 string is required"}), 400

        
        fpath = decode_b64_file(b64_str)
        logger.info(f"Decoded file saved at: {fpath}")

        
        txt_output = extract_text_file(fpath, lang=language)
        logger.info("OCR completed successfully.")

        
        patient_data, test_data = analyze_test_data(txt_output)

        
        response = {
            "patient_info": patient_data,
            "test_results": test_data
        }
        return jsonify(response), 200

    except Exception as ex:
        logger.error(f"Error in process_base64 endpoint: {ex}")
        return jsonify({"error": str(ex)}), 500


if __name__ == '__main__':
    
    os.makedirs('decoded_files', exist_ok=True)
    
    
    app.run(debug=True, host='0.0.0.0', port=5000)
