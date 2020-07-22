from collections import Counter
from IPython.core.display import display, HTML
import json 
import numpy as np
import pandas as pd
import requests
import re
import string
import spacy
from IPython.core.display import display, HTML


def disp(html):
    display(HTML(html))


def get_json(filepath):
    with open(filepath, 'r') as fp:
        return json.load(fp) 


def make_alpha(text):
    chars = [char for char in text if char.isalpha() or char in [' ', '\n']]
    string =  "".join(chars).lower()
    return re.sub(r"\s{2,}|\n", " ", string)


def get_paper_text(cord_uid, meta, data_dir):
    
    # find entry and collect json text files
    meta_entry = meta[meta.cord_uid == cord_uid].iloc[0]
    json_results = []
    if not pd.isna(meta_entry.pmc_json_files):
        json_results.append(get_json(data_dir + meta_entry.pmc_json_files))
    if not pd.isna(meta_entry.pdf_json_files):
        if ';' in meta_entry.pdf_json_files:
            for json_file in meta_entry.pdf_json_files.split(';'):
                json_results.append(get_json(data_dir + json_file.strip()))
        else:
            json_results.append(get_json(data_dir + meta_entry.pdf_json_files))
            
    # loop through json text files and build paper text
    paper_text = ""
    section_headers = []
    for result in json_results:
        if len(result["body_text"]) <= 1:
            continue
        for body_text in result["body_text"]:

            alpha_paper_text = make_alpha(paper_text)
            alpha_result_text = make_alpha(body_text["text"])
            already_in = False
            for i in range(3):
                if alpha_result_text[i*20+20:i*20+120] in alpha_paper_text:
                    already_in = True
                    break

            if not already_in:
                if not body_text["section"].lower() in section_headers:
                    section_headers.append(body_text['section'].lower())
                    paper_text += f"{body_text['section'].lower()}\n\n"
                paper_text += f"{body_text['text'].lower()}\n\n"

    if len(paper_text) < 2500:
        return ""

    if not pd.isna(meta_entry.abstract) and paper_text:
        alpha_paper_text = make_alpha(paper_text)
        alpha_abstract = make_alpha(meta_entry.abstract)
        already_in = False
        for i in range(3):
            if alpha_abstract[i*20+20:i*20+120] in alpha_paper_text:
                already_in = True
                break
        
        if not already_in:
            paper_text = f"{meta_entry.abstract.lower()}\n\n{paper_text}"
        
    return paper_text


accepted_tokens = ["amod", "compound", "npadvmod", "prep", "det", "compound", "punct", "nummod", "nsubj", "pobj"]

def extract_text_features(paper_text, doc):

    results = { 
        "quantities": [],
        "cardinals": [],
        "percents": [],
        "gpes": [],
    }
    
    for idx, ent in enumerate(doc.ents):
        
        is_counter = False
        if ent.label_ is "CARDINAL" and ent.text.isnumeric():
            try: 
                int_n = int(ent.text)
            except:
                continue
            next_30 = [ent.text for ent in doc.ents[idx+1:idx+21]]
            next_10 = [ent.text for ent in doc.ents[idx+1:idx+6]]
            if str(int_n + 1) in next_10:
                is_counter = True
            elif str(int_n + 1) in next_30 and str(int_n + 2) in next_30:
                is_counter = True
                
        if is_counter:
            continue
        
        if re.sub(r",|\.", "", ent.text).isnumeric() or ent.label_ is "CARDINAL":
            
            if ent.text[:2] in ["19", "20"] and ent.label_ is "DATE":
                results["cardinals"].append(ent.text)
                continue
            elif paper_text[ent.start_char - 1] in ['£','$','€']:
                results["quantities"].append((ent.text, paper_text[ent.start_char - 1]))
                continue
            
            quantity_of = None
            for i in range(10):
                if len(doc) <= ent.end + i:
                    break
                token = doc[ent.end + i]
                if token.tag_ == "NNS" and not token.dep_ == "compound":
                    quantity_of = token.text
                    break
                elif token.dep_ in accepted_tokens and not token.text in ['.', "in"]:
                    continue
                else:
                    break
                    
            if quantity_of is None:
        
                tokens_to_check = 0
                of_found = False
                while tokens_to_check <= 20:
                    token = doc[ent.start - tokens_to_check - 1]
                    if token.text == "of":
                        of_found=True
                        break
                    elif token.text in ['.', '(', '[', '{']:
                        break
                    else:
                        tokens_to_check += 1

                if of_found:
                    for i in range(tokens_to_check):
                        if len(doc) <= ent.start + i:
                            break
                        token = doc[ent.start - tokens_to_check + i]
                        if token.tag_ == "NNS" and not token.dep_ == "compound":
                            quantity_of = token.text
                            break
                        elif token.dep_ in accepted_tokens and not token.text in ['.', "in"]:
                            continue
                        else:
                            break
                
            if not quantity_of is None:
                results["quantities"].append((ent.text, quantity_of))  
            else:
                results["cardinals"].append(ent.text)

        if ent.label_ is "PERCENT":
            results["percents"].append(ent.text)

        if ent.label_ is "GPE" and ent.text.isalpha():
            results["gpes"].append(ent.text)
    
    plural_nouns = []
    for token in doc:
        if token.tag_ == "NNS" or token.ent_type_ in ["NORP", "GPE"]:
            plural_nouns.append((token.text))
            
    results["plural_nouns"] = Counter(plural_nouns).most_common()

    return results
    

def get_strength_of_evidence(text, doc):
    
    features = extract_text_features(text, doc)
    
    all_quantity_nouns = [noun for _, noun in features["quantities"]]
    most_common_nouns = Counter(all_quantity_nouns).most_common()
    mul_ref_nouns = [noun for noun, references in most_common_nouns
                     if references > 2]
    quantities_dict = {}
    for amount, noun in features["quantities"]:
        if not amount.isnumeric() or not noun in mul_ref_nouns:
            continue
        if not noun in quantities_dict.keys():
            if float(amount) > 9:
                quantities_dict[noun] = amount
        elif amount > quantities_dict[noun]:
            quantities_dict[noun] = amount
    
    accepted_nouns = [noun for noun, mentions in features["plural_nouns"][:10]
                      if mentions > 5]
    
    results = ""
    for noun in quantities_dict.keys():
        if noun in accepted_nouns:
            results += f"{noun}: {quantities_dict[noun]}, "
    
    locations = []
    for gpe, count in Counter(features["gpes"]).most_common():
        if count > 2:
            locations.append(gpe.title())
    if locations:
        results += f"Locations: {', '.join(locations)}"
                       
    return results


study_design_keywords = {
    r"meta\W?analysis": 'systematic review and metaanalysis',
    r"systematic\W(literature)?review": 'systematic review and metaanalysis',
    r"literature review": 'systematic review and metaanalysis',
    r"scoping\Wreview": 'systematic review and metaanalysis',
    r"case\Wseries": 'case series',
    r"cross\Wsectional": "crosssectional study",
    r"retrospective\W.{,20}cohort": 'retrospective observational study',
    r"longitudinal\W.{,20}cohort": 'retrospective observational study',
    r"retrospective\W.{,20}stud[iy]": 'retrospective observational study',
    r"retrospective\W.{,20}review": 'retrospective observational study',
    r"retrospective\W.{,20}analysis": 'retrospective observational study',
    r"prospective\W.{,20}cohort": 'prospective observational study',
    r"prospective\W.{,20}stud[iy]": 'prospective observational study',
    r"prospective\W.{,20}review": 'prospective observational study',
    r"prospective\W.{,20}analysis": 'prospective observational study',
    r"simulat(e|ion)": 'simulation',
    r"modell?ing": 'simulation',
    r"model\Wbased": 'simulation',
    r"mathematical model": "simulation",
    r"machine\Wlearning": "simulation",
}

study_design_regexs = [
    r"this (?!.{{,100}} a )(?!.{{,100}} existing )(?!.{{,100}} other ).{{,100}}{study_design}",
    r"our (?!.{{,100}} a )(?!.{{,100}} existing )(?!.{{,100}} other ).{{,100}}{study_design}",
    r"the present .{{,100}}{study_design}",
    r"we( have)? conduct(ed)? .{{,200}}{study_design}",
    r"we( have)? perform(ed)? .{{,200}}{study_design}",
    r"we( have)? implement(ed)? .{{,200}}{study_design}",
    r"we( have)? appl(y|ied) .{{,200}}{study_design}",
    r"we( have)? use[\sd] .{{,200}}{study_design}",
    r"{study_design}.{{,200}} was conducted",
    r"{study_design}.{{,200}} was performed",
    r"{study_design}.{{,200}} was implemented",
    r"{study_design}.{{,200}} was applied",
    r"{study_design}.{{,200}} was used",
    r"we present .{{,100}}{study_design}",
    r"we estimated .{{,200}}{study_design}",
    r"we confirmed (?!.{{,200}} a )(?!.{{,100}} existing )(?!.{{,100}} other ).{{,100}}{study_design}",
    r"we tested (?!.{{,200}} a )(?!.{{,100}} existing )(?!.{{,100}} other ).{{,100}}{study_design}",
    r"based on .{{,100}}{study_design}",
    r"design\W .{{,100}}{study_design}",
    r"method[s\W].{{,100}}{study_design}"
]

design_keyword_lists = {}
for keyword, study_design in study_design_keywords.items():
    if study_design in design_keyword_lists.keys():
        design_keyword_lists[study_design].append(keyword)
    else:
        design_keyword_lists[study_design] = [keyword]
        
def count_study_design_mentions(paper_text):

    results = {}
    for study_design in design_keyword_lists.keys():
        results[study_design] = 0

    for study_design, keyword_list in design_keyword_lists.items():
        for keyword in keyword_list:
            keyword_re = [design_re.format(study_design=keyword)
                          for design_re in study_design_regexs]
            keyword_p = re.compile("|".join(keyword_re))
            results[study_design] += len([hit for hit in keyword_p.finditer(paper_text)])
    return results


stats_regexs = [
    r"\Wci\W", r"p\s?<", r"n\s?=", r"p\s?=", r"\Wiqr\W", r"interquartile",
    r"standard rdeviation", r"\Wsd\W", r"median", r"p\Wvalue", r"pearson", 
    r"±", r"≥", r"≦", r"≤", r"χ"
]


def count_statistical_features(text):
    stats_p = re.compile("|".join(stats_regexs))
    return len([hit for hit in stats_p.finditer(text.lower())])


title_keywords = {
    r"meta\W?analysis": 'systematic review and metaanalysis',
    r"systematic\W(literature)?review": 'systematic review and metaanalysis',
    r"literature review": 'systematic review and metaanalysis',
    r"scoping\Wreview": 'systematic review and metaanalysis',
    r"simulat(e|ion)": 'simulation',
    r"modell?ing": 'simulation',
    r"model\Wbased": 'simulation',
    r"mathematical model": "simulation",
    r"machine\Wlearning": "simulation",
    r"case\Wseries": 'case series',
    r"cross\Wsectional": "crosssectional study",
    r"retrospective cohort": 'retrospective observational study',
    r"retrospective .{,20}stud[iy]": 'retrospective observational study',
    r"regression": "ecological regression",
    r"least squares": "ecological regression",
}


def assign_type_from_title(title):
    for keyword, study_design in title_keywords.items():
        if re.search(keyword, title.lower()):
            return study_design
    return None

design_types = np.array([key for key in design_keyword_lists.keys()])

model_terms = ["predict", "calculat", "fit", "apply", "param", "evaluat", "analy"]

model_regexs = []
for term in model_terms:
    model_regexs.append(f"{term}.{{,200}}model|model.{{,200}}{term}")

model_p = re.compile("|".join(model_regexs))


def assign_type_from_text(paper_text):

    if not len(paper_text):
        return None

    if re.search("letter to( the)? editor", paper_text):
        return "editorial"

    study_design_mentions = count_study_design_mentions(paper_text)
    design_counts = np.array(
        [n_mentions for n_mentions in study_design_mentions.values()]
    )
    # if there's only one type of study design mentioned in the text
    if (design_counts > 0).sum() == 1:
        return [design for design, count in study_design_mentions.items() 
                if count > 0][0]
    elif study_design_mentions["systematic review and metaanalysis"]:
        return "systematic review and metaanalysis"
    elif study_design_mentions["prospective observational study"]:
        return "prospective observational study"
    elif study_design_mentions["retrospective observational study"]:
        return "retrospective observational study"
    elif (np.array(design_counts) > 2).sum():
        return [design for design, count in study_design_mentions.items() 
                if count > 2][0]
    if (np.array(design_counts) > 0).sum():
        return [design for design, count in study_design_mentions.items() 
                if count > 0][0]
                          
    modelling_mentions = len([match for match in model_p.finditer(paper_text)])
    if modelling_mentions > 5:
        return "simulation"
        
    stats_mentions = count_statistical_features(paper_text)
    follow_up = True if re.search(r"follow(ing|ed)?\Wup", paper_text) else False
    
    method_p = re.compile(r"\n\n.{,100}method.{,100}\n\n")
    methods_section = True if method_p.search(paper_text) else False

    results_p = re.compile(r"\n\n.{,100}result.{,100}\n\n")
    results_section = True if results_p.search(paper_text) else False
                          
    if (stats_mentions and follow_up) or (follow_up and results_section and methods_section):
        return "retrospective observational study"
    
    if stats_mentions or (methods_section and results_section):
        return "analytical study"
                          
    return "expert review"
    

def find_populations(text, doc, n_hits):
    
    subject_keywords = [r"\Apatients\Z", r"\Apeople\Z", r"\Apersons\Z", r"\Awomen\Z", 
                        r"\Amen\Z",  r"\Astaff\Z", r"\Aworkers\Z",  r"\Aindividuals\Z", 
                        r"\Aadults\Z", r"\Amembers\Z",  r"\Aprofessionals\Z", r"\Aproviders\Z",
                        r"\Aresidents\Z", r"\Agroups\Z", r"[cimz]ans\Z", r"ists\W", r"\Acommunities\Z", r"\Acountries\Z"]

    subject_p = re.compile("|".join(subject_keywords))
    population_mentions = {} 

    for token in doc:
        if subject_p.search(token.text):
            
            if not token.text in population_mentions.keys():
                population_mentions[token.text] = []
                
            check_token_idx = 1
            hit_words_f = []
            while token.i + check_token_idx < len(doc):

                current_token =  doc[token.i + check_token_idx]
                if current_token.pos_ in ["NOUN", "PROPN"] and current_token.dep_ in ["pobj", "dobj", "nmod", "nsubj" "acomp"]:
                    hit_words_f.append(current_token.text)
                    hit_string_f = f"{token.text} {' '.join(hit_words_f)}"
                    break
                elif current_token.pos_ in ["ADP", "ADJ", "DET", "NOUN", "ADV"]:
                    hit_words_f.append(current_token.text)
                    check_token_idx += 1
                elif current_token.pos_ == "VERB" and current_token.dep_ in  ["acl", "amod", "compound", "pcomp", "relcl"]:
                    hit_words_f.append(current_token.text)
                    check_token_idx += 1
                else:
                    hit_string_f = ""
                    break
            
            check_token_idx = -1
            hit_words_b = []
            while token.i + check_token_idx > 0:
                current_token =  doc[token.i + check_token_idx]
                correct_pos = current_token.pos_ in ["ADV", "ADJ", "PROPN", "NOUN"]
                not_poss = not current_token.dep_ in ["poss"] 
                is_hyph = current_token.tag_ == "HYPH"
                is_pcomp = current_token.dep_ == "pcomp"
                is_ok_verb = current_token.pos_ == "VERB" and current_token.dep_ == "amod"
                if (correct_pos and not_poss) or is_hyph or is_pcomp or is_ok_verb:
                    hit_words_b.append(current_token.text)
                    check_token_idx -= 1
                else:
                    break
            
            if hit_string_f:
                population_mentions[token.text].append(hit_string_f)
            if hit_words_b:
                hit_string_b = f"{' '.join(hit_words_b[::-1])} {token.text}"
                population_mentions[token.text].append(hit_string_b)
        
    output_strings = []
    for mentions in population_mentions.values():
        top_results = Counter(mentions).most_common()
        for result in top_results:
            if not "covid" in result[0] and result[1] > n_hits:
                output_strings.append(result[0])
                break
    
    return ", ".join(output_strings)


pop_keywords = {
    "Homeless": ["homeless", "underhoused"],
    "Substance Abusers": ["(substance|alcohol|drug|opioid).{,100}(use|abuse|depend)",
                          "addict", 
                          "narcotic"],
    "Incarcerated": ["criminal", "prison", 
                     "incarcer", "correctional", 
                     "judicial"],
    "Refugees": ["refugee", "displaced"],
    "Economically Vulnerable": ["unemploy", "ineqaulit", "pover", 
                                "hunger", "starv"],
    "Children": ["paed", "child", "infant", "baby", "toddler"],
    "Healthcare Workers": ["(health(\W?care)?|clinical|medical) (worker|provider|staff|team|professional)", 
                           "doctor", "nurse", "surgeon", "physician", "clinician"],
    "The Elderly": ["elderly", "old.{,10}(patient|people|person|men|adult|women)", "old age",
                    "geriatric", "pension", "retired", "age?ing", "frail"],
    "Mentally Ill": ["mental.{,20}ill", "psycholog"],
    "ICU Patients": ["patient.{,100}intensive\Wcare", "patient.{,100}icu",
                     "intensive\Wcare.{,100}patient", "icu.{,100}patient" ],
    "Parents": ["parent"],
    "Diabetics": ["diabetic"],
    "Hearing Impaired": ["hearing.{,100}(loss|impair)", "deaf"],
    "Epileptics": ["epilep"],
    "Cancer Patients": ["cancer"],
    "Caregivers": ["carer", "care\W?giver"],
    "Students": ["student"]
}


def find_populations_backup(text, n_hits):

    population_hits ={}
    for population in pop_keywords.keys():
        population_hits[population] = 0

    for population, keywords in pop_keywords.items():
        for keyword in keywords:
            hits = len([hit for hit in re.finditer(keyword, text)])
            population_hits[population] += hits
    
    results = []

    for population, hits in population_hits.items():
        if hits > n_hits:
            results.append(population)

    if results:
        return ", ".join(results)
    else:
        return "General Population"