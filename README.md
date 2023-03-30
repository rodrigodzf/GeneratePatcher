# GeneratePatcher

![output](https://user-images.githubusercontent.com/3747187/228944882-05a99609-e49b-4908-9cf5-613dc1196355.gif)

## About

GeneratePatcher is a python script that generates a Pure Data patcher using one of OpenAI's LLMs. It uses the OpenAI API to communicate with the LLM. The model can be set in the `config.yaml` file, as well as other settings.

## Requirements

Run the following command to install the dependencies:

```bash
pip install -r requirements.txt
```

## Usage

```bash
python generate_patcher.py
```

## Caveats

The generated patcher is often not correct. The commands are fed to Pure Data line by line, and it expects an answer of Pure Data after each command. Each command will be answered with an `ack`. If there is an error, Pure Data will send the error message, with a description of the error.

It is possible to fix some of these errors by providing this feedback to the LLM. This has to be done manually.

It is also possible that the generation will go beyond the maximum number of tokens. In this case, the patcher will be incomplete.

## Related projects

This demo was inspired by [this](https://github.com/gd3kr/BlenderGPT) and several hacks in the last week.
