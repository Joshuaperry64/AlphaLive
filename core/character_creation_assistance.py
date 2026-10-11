import openai

class CharacterCreationAssistance:
    def __init__(self, api_key):
        self.api_key = api_key
        openai.api_key = self.api_key

    def generate_character_details(self, prompt):
        try:
            response = openai.Completion.create(
                engine="text-davinci-003",
                prompt=prompt,
                max_tokens=500
            )
            return response.choices[0].text.strip()
        except Exception as e:
            print(f"[CharacterCreationAssistance] Error generating character details: {e}")
            return None
