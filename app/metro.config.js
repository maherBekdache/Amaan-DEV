// Lets the app use the shared analysis code in ../packages/core (same rules as the server).
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);
const packages = path.resolve(__dirname, "../packages");

config.watchFolders = [packages];
config.resolver.nodeModulesPaths = [path.resolve(__dirname, "node_modules")];
config.resolver.extraNodeModules = { "@amaan/core": path.join(packages, "core") };

module.exports = config;
